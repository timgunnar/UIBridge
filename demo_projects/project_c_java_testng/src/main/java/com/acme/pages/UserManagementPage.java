package com.acme.pages;

import org.openqa.selenium.WebDriver;
import com.acme.components.WebTable;
import com.acme.components.WebInput;
import com.acme.components.WebButton;

/**
 * UserManagementPage — 用户管理页面对象。
 * 聚合页面上的所有组件。
 */
public class UserManagementPage {
    private final WebDriver driver;
    public final WebTable userTable;
    public final WebInput searchBox;
    public final WebButton searchBtn;
    public final WebButton addBtn;

    public UserManagementPage(WebDriver driver) {
        this.driver = driver;
        this.userTable = new WebTable(driver, "user-table");
        this.searchBox = new WebInput(driver, "search-box");
        this.searchBtn = new WebButton(driver, "search-btn");
        this.addBtn = new WebButton(driver, "add-btn");
    }

    public void navigateTo() {
        driver.get("https://example.com/user/manage");
    }
}
