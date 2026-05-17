package com.fluent.builders;

/**
 * UserBuilder — 用户测试数据构建器 (Builder 模式)。
 */
public class UserBuilder {
    private String name = "张三";
    private String age = "25";
    private String role = "user";

    public UserBuilder withName(String name) { this.name = name; return this; }
    public UserBuilder withAge(String age) { this.age = age; return this; }
    public UserBuilder withRole(String role) { this.role = role; return this; }

    public String getName() { return name; }
    public String getAge() { return age; }
    public String getRole() { return role; }

    public UserBuilder build() { return this; }

    public static UserBuilder validUser() {
        return new UserBuilder().build();
    }

    public static UserBuilder adminUser() {
        return new UserBuilder().withRole("admin").build();
    }
}
