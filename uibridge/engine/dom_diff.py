"""DOM 差异引擎 — 对比操作前后 ARIA 快照，自动提取断言候选。支持结构化 ARIA 树比对。"""

import json
import re
from dataclasses import dataclass, field
from collections import Counter


@dataclass
class AriaNode:
    """ARIA 快照节点"""
    role: str = ""
    name: str = ""
    text: str = ""
    level: int = 0
    children: list["AriaNode"] = field(default_factory=list)
    attrs: dict = field(default_factory=dict)


@dataclass
class DiffEntry:
    """差异条目"""
    type: str  # added / removed / modified / text_changed / attr_changed / position_changed / url_changed
    element_selector: str = ""
    element_role: str = ""
    element_name: str = ""
    description: str = ""
    before: str = ""
    after: str = ""


@dataclass
class DOMDiffResult:
    """DOM 差异结果"""
    entries: list[DiffEntry] = field(default_factory=list)
    assertion_candidates: list[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return len(self.entries) > 0


class DOMDiffer:
    """对比两次 ARIA 快照，使用结构化 ARIA 树比较 + role 计数兜底"""

    def diff(self, before: str, after: str, url_before: str = "", url_after: str = "",
             layout_before: str = "{}", layout_after: str = "{}") -> DOMDiffResult:
        entries: list[DiffEntry] = []

        # URL 变化
        if url_before != url_after and url_after:
            entries.append(DiffEntry(
                type="url_changed",
                description=f"URL changed: {url_before} → {url_after}",
                before=url_before,
                after=url_after,
            ))

        # 尝试结构化 ARIA 树解析
        before_parsed = self._parse_aria_tree(before)
        after_parsed = self._parse_aria_tree(after)

        if before_parsed and after_parsed:
            self._diff_trees(before_parsed, after_parsed, entries)
        else:
            # 回退到 role 计数
            self._diff_role_counts(before, after, entries)

        # 布局位置变化检测
        self._diff_layout(layout_before, layout_after, entries)

        assertion_candidates = self._generate_assertion_candidates(entries, after)
        return DOMDiffResult(entries=entries, assertion_candidates=assertion_candidates)

    # ── ARIA 树解析 ─────────────────────────────

    def _parse_aria_tree(self, snapshot: str) -> list[AriaNode]:
        """将 ARIA 快照解析为结构化节点树"""
        if not snapshot:
            return []
        nodes = []
        lines = snapshot.split("\n")
        stack: list[tuple[int, AriaNode]] = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            # 检测缩进深度
            depth = len(line) - len(line.lstrip())

            # 提取 role — 支持两种格式:
            #   - role "name"          (ARIA snapshot 格式)
            #   - role=button name="X"  (属性格式)
            role_match = re.search(r'role[=:]\s*["\']?(\w+)', stripped, re.IGNORECASE)
            if role_match:
                role = role_match.group(1)
            else:
                # 回退: `- role "name"` 格式 — 行首破折号后第一个词
                dash_match = re.match(r'^[-*]\s+(\w+)', stripped)
                role = dash_match.group(1) if dash_match else "unknown"

            # 提取 name — 支持 `name="X"`, `name: "X"`, 或 `- role "X"` 中引号内文本
            name_match = re.search(r'name[=:]\s*["\']([^"\']+)["\']', stripped, re.IGNORECASE)
            if name_match:
                name = name_match.group(1)
            else:
                # 回退: `- role "Name"` — 提取 role 后的第一个引号字符串作为 name
                fallback_name = re.match(r'^[-*]\s*\w+\s+"([^"]*)"', stripped)
                name = fallback_name.group(1) if fallback_name else ""

            # 提取文本内容 — 排除已用作 name 的引号内容
            text_match = re.search(r'"([^"]*)"', stripped)
            text = text_match.group(1) if text_match else ""
            if text == name:
                # 若唯一引号字符串已被用作 name，则无独立 text
                text = ""

            # 提取其他属性
            attrs = {}
            for m in re.finditer(r'(\w+)[=:]\s*["\']([^"\']+)["\']', stripped):
                attrs[m.group(1)] = m.group(2)

            node = AriaNode(role=role, name=name, text=text, level=depth, attrs=attrs)

            # 构建树
            while stack and stack[-1][0] >= depth:
                stack.pop()
            if stack:
                stack[-1][1].children.append(node)
            else:
                nodes.append(node)
            stack.append((depth, node))

        return nodes

    # ── 树结构差异 ─────────────────────────────

    def _diff_trees(self, before_nodes: list[AriaNode], after_nodes: list[AriaNode],
                    entries: list[DiffEntry]):
        """比较两棵 ARIA 树的差异"""
        before_roles = Counter()
        after_roles = Counter()
        before_named: dict[str, AriaNode] = {}
        after_named: dict[str, AriaNode] = {}

        def _collect(node: AriaNode, counter: Counter, named: dict):
            counter[node.role] += 1
            if node.name:
                key = f"{node.role}:{node.name}"
                if key not in named:
                    named[key] = node
            for child in node.children:
                _collect(child, counter, named)

        for node in before_nodes:
            _collect(node, before_roles, before_named)
        for node in after_nodes:
            _collect(node, after_roles, after_named)

        # 新增的 role
        for role, count in after_roles.items():
            before_count = before_roles.get(role, 0)
            if count > before_count:
                entries.append(DiffEntry(
                    type="added", element_role=role,
                    description=f"New {role} element(s) appeared: {before_count} → {count}",
                ))

        # 删除的 role
        for role, count in before_roles.items():
            after_count = after_roles.get(role, 0)
            if count > after_count:
                entries.append(DiffEntry(
                    type="removed", element_role=role,
                    description=f"{role} element(s) removed: {count} → {after_count}",
                ))

        # 同名元素变化
        all_keys = set(before_named.keys()) | set(after_named.keys())
        for key in all_keys:
            b_node = before_named.get(key)
            a_node = after_named.get(key)

            if b_node and not a_node:
                entries.append(DiffEntry(
                    type="removed", element_role=b_node.role,
                    element_name=b_node.name,
                    description=f"Element '{b_node.name}' ({b_node.role}) removed",
                ))
            elif not b_node and a_node:
                entries.append(DiffEntry(
                    type="added", element_role=a_node.role,
                    element_name=a_node.name,
                    description=f"Element '{a_node.name}' ({a_node.role}) appeared",
                ))
            elif b_node and a_node:
                # 文本变化
                if b_node.text != a_node.text:
                    entries.append(DiffEntry(
                        type="text_changed", element_role=a_node.role,
                        element_name=a_node.name,
                        description=f"Text changed in '{a_node.name}': '{b_node.text}' → '{a_node.text}'",
                        before=b_node.text, after=a_node.text,
                    ))
                # 属性变化
                b_attr_str = str(sorted(b_node.attrs.items()))
                a_attr_str = str(sorted(a_node.attrs.items()))
                if b_attr_str != a_attr_str:
                    diff_attrs = {}
                    for ak, av in a_node.attrs.items():
                        if b_node.attrs.get(ak) != av:
                            diff_attrs[ak] = {"before": b_node.attrs.get(ak, ""), "after": av}
                    if diff_attrs:
                        attr_desc = ", ".join(
                            f"{k}: {v['before']} → {v['after']}" for k, v in diff_attrs.items()
                        )
                        entries.append(DiffEntry(
                            type="attr_changed", element_role=a_node.role,
                            element_name=a_node.name,
                            description=f"Attributes changed in '{a_node.name}': {attr_desc}",
                        ))

    # ── 布局位置变化检测 ───────────────────────

    def _diff_layout(self, layout_before: str, layout_after: str, entries: list[DiffEntry]):
        """比较两个快照的元素布局信息，检测位置/尺寸变化"""
        if not layout_before or not layout_after or layout_before == "{}" or layout_after == "{}":
            return
        try:
            before_map = json.loads(layout_before) if isinstance(layout_before, str) else layout_before
            after_map = json.loads(layout_after) if isinstance(layout_after, str) else layout_after
        except (json.JSONDecodeError, TypeError):
            return

        all_keys = set(before_map.keys()) | set(after_map.keys())
        for key in all_keys:
            bp = before_map.get(key, {})
            ap = after_map.get(key, {})
            if not bp or not ap:
                continue
            dx = abs(ap.get("x", 0) - bp.get("x", 0))
            dy = abs(ap.get("y", 0) - bp.get("y", 0))
            dw = abs(ap.get("w", 0) - bp.get("w", 0))
            dh = abs(ap.get("h", 0) - bp.get("h", 0))
            if dx > 10 or dy > 10 or dw > 10 or dh > 10:
                entries.append(DiffEntry(
                    type="position_changed",
                    element_name=key,
                    description=(
                        f"Element '{key}' position/size changed: "
                        f"({bp.get('x')},{bp.get('y')},{bp.get('w')}x{bp.get('h')}) → "
                        f"({ap.get('x')},{ap.get('y')},{ap.get('w')}x{ap.get('h')})"
                    ),
                ))

    # ── Role 计数兜底 ──────────────────────────

    def _diff_role_counts(self, before: str, after: str, entries: list[DiffEntry]):
        before_roles = self._extract_roles(before)
        after_roles = self._extract_roles(after)

        for role, after_count in after_roles.items():
            before_count = before_roles.get(role, 0)
            if after_count > before_count:
                entries.append(DiffEntry(
                    type="added", element_role=role,
                    description=f"New {role}(s) appeared: {before_count} → {after_count}",
                ))

        for role, before_count in before_roles.items():
            after_count = after_roles.get(role, 0)
            if before_count > after_count:
                entries.append(DiffEntry(
                    type="removed", element_role=role,
                    description=f"{role}(s) removed: {before_count} → {after_count}",
                ))

    # ── 断言候选生成 ──────────────────────────

    def _generate_assertion_candidates(self, entries: list[DiffEntry], snapshot: str) -> list[str]:
        candidates = []
        for entry in entries:
            if entry.type == "url_changed":
                candidates.append(f"assert page.url == \"{entry.after}\"")
            elif entry.type == "added":
                if entry.element_name:
                    candidates.append(f"assert element '{entry.element_name}' ({entry.element_role}) is visible")
                else:
                    candidates.append(f"assert count of {entry.element_role} elements increased")
            elif entry.type == "removed":
                if entry.element_name:
                    candidates.append(f"assert element '{entry.element_name}' ({entry.element_role}) is absent")
                else:
                    candidates.append(f"assert count of {entry.element_role} elements decreased")
            elif entry.type == "text_changed":
                if entry.element_name:
                    candidates.append(
                        f"assert text of '{entry.element_name}' == \"{entry.after}\""
                    )
            elif entry.type == "attr_changed":
                candidates.append(f"assert {entry.description}")
            elif entry.type == "position_changed":
                candidates.append(f"assert layout of '{entry.element_name}' is stable")

        # 补充启发式断言 — 使用标准格式以匹配 parse_assertion_candidate 的 6 种模式
        if "button" in snapshot.lower():
            candidates.append("assert element 'action_button' (button) is visible")
        if any(t in snapshot.lower() for t in ("table", "grid", "list")):
            candidates.append("assert element 'result_list' (table) is visible")
        if "link" in snapshot.lower():
            candidates.append("assert element 'navigation_links' (link) is visible")

        return candidates

    # ── Role 提取工具 ──────────────────────────

    def _extract_roles(self, snapshot: str) -> dict[str, int]:
        roles: dict[str, int] = {}
        for match in re.finditer(r'(?:role|Role)\s*[=:]\s*["\']?(\w+)', snapshot):
            role = match.group(1).lower()
            roles[role] = roles.get(role, 0) + 1
        for match in re.finditer(r'^\s*-\s+(\w+)', snapshot, re.MULTILINE):
            roles[match.group(1).lower()] = roles.get(match.group(1).lower(), 0) + 1
        return roles
