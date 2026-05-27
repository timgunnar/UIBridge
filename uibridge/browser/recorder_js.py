"""录制引擎 JavaScript 注入脚本 — DOM 事件监听与 Python 桥接"""

RECORDER_JS = r"""
(() => {
    if (window.__uibridge_recorder_ready) return;
    window.__uibridge_recorder_ready = true;

    function describe(el) {
        if (!el || el === document || el === document.body) return {};
        const tag = (el.tagName || '').toLowerCase();
        const rect = el.getBoundingClientRect ? el.getBoundingClientRect() : {};
        let label = el.getAttribute('aria-label') || el.getAttribute('placeholder')
                 || el.getAttribute('title') || '';
        if (!label) {
            const prev = el.previousElementSibling;
            if (prev && prev.tagName === 'LABEL')
                label = (prev.textContent || '').trim().substring(0, 50);
        }
        if (!label) label = (el.textContent || '').trim().substring(0, 50);
        return {
            tag,
            id: el.id || '',
            name: el.getAttribute('name') || '',
            role: el.getAttribute('role') || '',
            ariaLabel: el.getAttribute('aria-label') || '',
            dataTestid: el.getAttribute('data-testid') || '',
            dataModule: el.getAttribute('data-module') || '',
            css: el.id ? ('#' + el.id)
               : (el.getAttribute('data-testid') ? '[data-testid="' + el.getAttribute('data-testid') + '"]'
               : (el.getAttribute('data-module') ? '[data-module="' + el.getAttribute('data-module') + '"]' : '')),
            label,
            value: el.value || '',
            x: Math.round(rect.x || 0),
            y: Math.round(rect.y || 0),
            w: Math.round(rect.width || 0),
            h: Math.round(rect.height || 0),
        };
    }

    function visible(el) {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        return style.display !== 'none' && style.visibility !== 'hidden'
            && !!(el.offsetParent || el.getClientRects().length);
    }

    // ── 点击 ──────────────────────────────────
    document.addEventListener('click', (e) => {
        const el = e.target;
        if (!visible(el)) return;
        const d = describe(el);
        d.url = location.href;
        window.__uibridge_report('click', JSON.stringify(d));
    }, true);

    // ── 双击 ──────────────────────────────────
    document.addEventListener('dblclick', (e) => {
        const el = e.target;
        if (!visible(el)) return;
        const d = describe(el);
        d.url = location.href;
        window.__uibridge_report('dblclick', JSON.stringify(d));
    }, true);

    // ── 输入 / 选择变更（捕获阶段以穿透 Shadow DOM）──
    document.addEventListener('change', (e) => {
        const el = e.target;
        if (!visible(el)) return;
        const tag = (el.tagName || '').toLowerCase();
        const typ = (el.getAttribute('type') || '').toLowerCase();
        const d = describe(el);
        d.url = location.href;
        if (tag === 'input' && typ === 'checkbox') {
            d.checked = el.checked;
            window.__uibridge_report('checkbox_change', JSON.stringify(d));
        } else if (tag === 'input' && typ === 'radio') {
            d.checked = el.checked;
            window.__uibridge_report('radio_change', JSON.stringify(d));
        } else if (tag === 'input' && typ === 'file') {
            const files = [];
            for (const f of (el.files || [])) files.push(f.name);
            d.files = files;
            window.__uibridge_report('file_input', JSON.stringify(d));
        } else if (tag === 'input' && typ === 'range') {
            d.value = el.value;
            window.__uibridge_report('range_change', JSON.stringify(d));
        } else if (tag === 'input' || tag === 'textarea') {
            window.__uibridge_report('input', JSON.stringify(d));
        } else if (tag === 'select') {
            if (el.multiple) {
                const selected = [];
                for (const o of el.selectedOptions) selected.push(o.value || o.text);
                d.values = selected;
            }
            window.__uibridge_report('select', JSON.stringify(d));
        }
    }, true);

    // ── 键盘（功能键 + 组合键，普通字符不在此记录）──
    const _FUNCTIONAL_KEYS = new Set([
        'Enter', 'Tab', 'Escape', 'Backspace', 'Delete',
        'ArrowLeft', 'ArrowUp', 'ArrowRight', 'ArrowDown',
        'PageUp', 'PageDown', 'Home', 'End',
        'F1', 'F2', 'F3', 'F4', 'F5', 'F6',
        'F7', 'F8', 'F9', 'F10', 'F11', 'F12',
    ]);
    document.addEventListener('keydown', (e) => {
        const is_mod = e.ctrlKey || e.metaKey || e.altKey;
        // 记录：功能键 OR 带修饰键的组合键。普通可打印字符由 input/change 事件记录。
        if (!_FUNCTIONAL_KEYS.has(e.key) && !is_mod) return;
        // 仅修饰键（Ctrl/Shift/Alt/Meta 单独按下）不记录
        if (e.key === 'Control' || e.key === 'Shift' || e.key === 'Alt' || e.key === 'Meta') return;
        const el = e.target;
        const d = el ? describe(el) : {};
        d.url = location.href;
        window.__uibridge_report('keydown', JSON.stringify({
            key: e.key,
            code: e.code,
            ctrlKey: e.ctrlKey || false,
            shiftKey: e.shiftKey || false,
            altKey: e.altKey || false,
            metaKey: e.metaKey || false,
            target: d,
        }));
    }, true);

    // ── 右键 ──────────────────────────────────
    document.addEventListener('contextmenu', (e) => {
        const el = e.target;
        if (!visible(el)) return;
        const d = describe(el);
        d.url = location.href;
        window.__uibridge_report('rightclick', JSON.stringify(d));
    }, true);

    // ── 悬停（防抖 300ms）─────────────────────
    let _hover_timer = null;
    let _last_hover_el = null;
    document.addEventListener('mouseenter', (e) => {
        const el = e.target;
        if (!visible(el) || el === _last_hover_el) return;
        _last_hover_el = el;
        if (_hover_timer) clearTimeout(_hover_timer);
        _hover_timer = setTimeout(() => {
            const d = describe(el);
            d.url = location.href;
            window.__uibridge_report('hover', JSON.stringify(d));
        }, 300);
    }, true);

    // ── 拖拽 ──────────────────────────────────
    let _drag_source = null;
    document.addEventListener('dragstart', (e) => {
        const el = e.target;
        if (!visible(el)) return;
        _drag_source = describe(el);
        _drag_source.url = location.href;
    }, true);
    document.addEventListener('dragover', (e) => {
        e.preventDefault();
    }, true);
    document.addEventListener('drop', (e) => {
        e.preventDefault();
        const el = e.target;
        if (!visible(el) || !_drag_source) return;
        const target_desc = describe(el);
        target_desc.url = location.href;
        window.__uibridge_report('drop', JSON.stringify({
            source: _drag_source,
            target: target_desc,
        }));
        _drag_source = null;
    }, true);

    // ── 滚动（防抖 500ms）─────────────────────
    let _scroll_timer = null;
    let _last_scroll = {x: 0, y: 0};
    document.addEventListener('scroll', (e) => {
        if (_scroll_timer) clearTimeout(_scroll_timer);
        _scroll_timer = setTimeout(() => {
            const s = {x: Math.round(window.scrollX), y: Math.round(window.scrollY)};
            if (Math.abs(s.x - _last_scroll.x) > 50 || Math.abs(s.y - _last_scroll.y) > 50) {
                _last_scroll = s;
                window.__uibridge_report('scroll', JSON.stringify({...s, url: location.href}));
            }
        }, 500);
    }, true);

    // ── 表单提交 ──────────────────────────────
    document.addEventListener('submit', (e) => {
        const el = e.target;
        const tag = (el.tagName || '').toLowerCase();
        if (tag !== 'form') return;
        const formId = el.id || el.getAttribute('name') || '';
        const action = el.getAttribute('action') || '';
        const method = el.getAttribute('method') || 'get';
        const inputs = [];
        el.querySelectorAll('input,select,textarea').forEach(ctl => {
            const ctlTag = (ctl.tagName || '').toLowerCase();
            const ctlType = (ctl.getAttribute('type') || 'text').toLowerCase();
            const name = ctl.getAttribute('name') || ctl.id || '';
            if (!name) return;
            if (ctlTag === 'input' && (ctlType === 'submit' || ctlType === 'button')) return;
            inputs.push({name, value: ctl.value || '', tag: ctlTag, type: ctlType});
        });
        window.__uibridge_report('submit', JSON.stringify({
            id: formId, action, method, inputs,
            url: location.href,
        }));
    }, true);

    // ── 焦点变化（Tab 键导航）───────────────
    document.addEventListener('focusin', (e) => {
        const el = e.target;
        if (!el) return;
        const tag = (el.tagName || '').toLowerCase();
        const focusable = ['input', 'select', 'textarea', 'button', 'a'];
        if (!focusable.includes(tag) && el.getAttribute('tabindex') == null) return;
        const d = describe(el);
        d.url = location.href;
        window.__uibridge_report('focus', JSON.stringify(d));
    }, true);

    // ── 剪贴板 ──────────────────────────────
    document.addEventListener('copy', (e) => {
        const el = e.target;
        const d = el ? describe(el) : {};
        const selection = window.getSelection ? window.getSelection().toString().substring(0, 200) : '';
        d.url = location.href;
        d.clipData = selection;
        window.__uibridge_report('clipboard', JSON.stringify({action: 'copy', target: d}));
    }, true);
    document.addEventListener('cut', (e) => {
        const el = e.target;
        const d = el ? describe(el) : {};
        const selection = window.getSelection ? window.getSelection().toString().substring(0, 200) : '';
        d.url = location.href;
        d.clipData = selection;
        window.__uibridge_report('clipboard', JSON.stringify({action: 'cut', target: d}));
    }, true);
    document.addEventListener('paste', (e) => {
        const el = e.target;
        const d = el ? describe(el) : {};
        d.url = location.href;
        const clipData = (e.clipboardData && e.clipboardData.getData('text'))
            ? e.clipboardData.getData('text').substring(0, 200)
            : '';
        d.clipData = clipData;
        window.__uibridge_report('clipboard', JSON.stringify({action: 'paste', target: d}));
    }, true);

    // ── 原生弹窗拦截 ────────────────────────
    if (!window.__uibridge_dialog_patched) {
        window.__uibridge_dialog_patched = true;
        const _orig_alert = window.alert;
        const _orig_confirm = window.confirm;
        const _orig_prompt = window.prompt;
        window.alert = function(msg) {
            window.__uibridge_report('dialog', JSON.stringify({
                type: 'alert', message: String(msg || ''),
            }));
            return _orig_alert.call(window, msg);
        };
        window.confirm = function(msg) {
            window.__uibridge_report('dialog', JSON.stringify({
                type: 'confirm', message: String(msg || ''),
            }));
            return _orig_confirm.call(window, msg);
        };
        window.prompt = function(msg, defaultText) {
            window.__uibridge_report('dialog', JSON.stringify({
                type: 'prompt', message: String(msg || ''),
                defaultValue: String(defaultText || ''),
            }));
            return _orig_prompt.call(window, msg, defaultText);
        };
    }

    // ── SPA 路由变化 — 用 console.log 桥接（安全线程可捕获）──
    let _last_url = location.href;
    function _report_url_change() {
        if (location.href !== _last_url) {
            _last_url = location.href;
            console.log('__uibridge_nav__:' + JSON.stringify({url: location.href}));
        }
    }
    window.addEventListener('popstate', _report_url_change, true);
    window.addEventListener('hashchange', _report_url_change, true);

    // 拦截 history.pushState / replaceState（React Router / Vue Router 依赖它们）
    const _orig_pushState = history.pushState;
    const _orig_replaceState = history.replaceState;
    history.pushState = function(...args) {
        _orig_pushState.apply(this, args);
        _report_url_change();
    };
    history.replaceState = function(...args) {
        _orig_replaceState.apply(this, args);
        _report_url_change();
    };

    // Turbolinks / Turbo 导航检测
    document.addEventListener('turbolinks:load', _report_url_change, true);
    document.addEventListener('turbo:load', _report_url_change, true);
    document.addEventListener('turbolinks:visit', _report_url_change, true);
    document.addEventListener('turbo:visit', _report_url_change, true);

    // ── MutationObserver：动态内容变化（去抖合并） ─────────
    let _mut_pending = null;        // {added, removed, attrChanged, url}
    let _mut_timer = null;
    let _mut_first_ts = 0;
    const MUT_DEBOUNCE_MS = 500;    // 去抖窗口
    const MUT_MAX_HOLD_MS = 2000;   // 最长持有（防止持续动画/轮询导致不刷新）

    function _flush_mutations() {
        if (_mut_timer) { clearTimeout(_mut_timer); _mut_timer = null; }
        if (_mut_pending && (_mut_pending.added > 0 || _mut_pending.removed > 0 || _mut_pending.attrChanged > 0)) {
            window.__uibridge_report('mutation', JSON.stringify(_mut_pending));
        }
        _mut_pending = null;
        _mut_first_ts = 0;
    }

    function _schedule_mutation_flush() {
        if (_mut_timer) clearTimeout(_mut_timer);
        _mut_timer = setTimeout(_flush_mutations, MUT_DEBOUNCE_MS);
    }

    // KB 驱动噪声过滤：检查元素是否含有白名单属性（向上查 5 层）
    function _has_locator_attr(el) {
        let node = el;
        const attrs = window.__uibridge_locator_attrs;
        for (let i = 0; i < 5 && node && node !== document.body; i++) {
            if (node.getAttribute && attrs) {
                for (const attr of attrs) {
                    if (node.hasAttribute(attr)) return true;
                }
            }
            node = node.parentElement;
        }
        return false;
    }

    // 检查一批 mutation 中是否至少有一个受影响元素含有定位器属性
    function _mutation_batch_has_locator(mutations) {
        const attrs = window.__uibridge_locator_attrs;
        if (!attrs || attrs.length === 0) return true; // 无白名单 → 不过滤
        for (const m of mutations) {
            if (m.type === 'attributes') {
                if (m.target && m.target.nodeType === 1 && _has_locator_attr(m.target)) return true;
            } else {
                for (const node of m.addedNodes) {
                    if (node.nodeType === 1 && _has_locator_attr(node)) return true;
                }
                for (const node of m.removedNodes) {
                    if (node.nodeType === 1 && _has_locator_attr(node)) return true;
                }
            }
        }
        return false;
    }

    const _mo = new MutationObserver((mutations) => {
        // 噪声过滤：检查整批 mutation 是否至少命中一个白名单元素
        if (!_mutation_batch_has_locator(mutations)) return;
        let added = 0, removed = 0, attr_changed = 0;
        for (const m of mutations) {
            added += m.addedNodes.length;
            removed += m.removedNodes.length;
            if (m.type === 'attributes') attr_changed++;
        }
        if (added === 0 && removed === 0 && attr_changed === 0) return;
        if (!_mut_pending) {
            _mut_pending = {added: 0, removed: 0, attrChanged: 0, url: location.href};
            _mut_first_ts = Date.now();
        }
        _mut_pending.added += added;
        _mut_pending.removed += removed;
        _mut_pending.attrChanged += attr_changed;
        _mut_pending.url = location.href;
        // 超长持有保护
        if (Date.now() - _mut_first_ts > MUT_MAX_HOLD_MS) {
            _flush_mutations();
        } else {
            _schedule_mutation_flush();
        }
    });

    // 优先观察 documentElement（始终存在），body 异步就绪后再追加
    function _start_observing() {
        const target = document.body || document.documentElement;
        _mo.observe(target, {
            childList: true, subtree: true, attributes: true,
            attributeFilter: ['class', 'style', 'disabled', 'aria-expanded', 'aria-selected', 'hidden'],
        });
        if (!document.body) {
            // body 尚未就绪，轮询等待
            const _check = setInterval(() => {
                if (document.body) {
                    clearInterval(_check);
                    _mo.observe(document.body, {
                        childList: true, subtree: true, attributes: true,
                        attributeFilter: ['class', 'style', 'disabled', 'aria-expanded', 'aria-selected', 'hidden'],
                    });
                }
            }, 50);
            setTimeout(() => clearInterval(_check), 10000); // 超时保护
        }
    }
    _start_observing();

    // 暴露 flush 函数供 Python 端在 stop 时调用
    window.__uibridge_flush_mutations = _flush_mutations;

    // ── Shadow DOM 辅助：遍历所有 shadow root 执行查询 ──
    function _query_all_deep(root, selector) {
        const results = [];
        try {
            const els = root.querySelectorAll(selector);
            for (const el of els) results.push(el);
        } catch(e) {}
        // 递归遍历 shadow roots
        const all_els = root.querySelectorAll('*');
        for (const el of all_els) {
            if (el.shadowRoot) {
                const deep = _query_all_deep(el.shadowRoot, selector);
                for (const d of deep) results.push(d);
            }
        }
        return results;
    }

    // ── 布局信息采集（供快照位置对比，含 Shadow DOM）──
    window.__uibridge_get_layout = function(selector) {
        const q = selector || '[id],[data-testid],[data-module],[role],button,input,select,textarea,table,[aria-label]';
        const els = _query_all_deep(document, q);
        const result = {};
        const seen = new Set();
        for (const el of els) {
            if (!visible(el)) continue;
            const key = el.id || el.getAttribute('data-testid') || el.getAttribute('data-module')
                     || el.getAttribute('aria-label') || el.getAttribute('name') || el.getAttribute('role') || el.tagName;
            if (!key || seen.has(key)) continue;
            seen.add(key);
            const r = el.getBoundingClientRect();
            result[key] = {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)};
        }
        return JSON.stringify(result);
    };
})()
"""
