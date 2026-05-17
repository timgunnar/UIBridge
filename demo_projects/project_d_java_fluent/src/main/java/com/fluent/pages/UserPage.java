package com.fluent.pages;

import org.openqa.selenium.WebDriver;
import com.fluent.elements.PageElement;

/**
 * UserPage — 流式页面对象。
 * 每个方法返回 this，支持链式调用。
 * 使用 data-test 属性定位。
 */
public class UserPage {
    private final WebDriver driver;
    private final PageElement searchInput;
    private final PageElement searchButton;
    private final PageElement addButton;
    private final PageElement saveButton;
    private final PageElement userTable;
    private final PageElement nameInput;

    public UserPage(WebDriver driver) {
        this.driver = driver;
        this.searchInput = new PageElement(driver, "//*[@data-test='search-input']");
        this.searchButton = new PageElement(driver, "//*[@data-test='search-btn']");
        this.addButton = new PageElement(driver, "//*[@data-test='add-btn']");
        this.saveButton = new PageElement(driver, "//*[@data-test='save-btn']");
        this.userTable = new PageElement(driver, "//*[@data-test='user-table']");
        this.nameInput = new PageElement(driver, "//*[@data-test='name-input']");
    }

    public UserPage navigateTo(String url) {
        driver.get(url);
        return this;
    }

    public UserPage searchFor(String keyword) {
        searchInput.enter(keyword);
        searchButton.click();
        return this;
    }

    public UserPage clickAdd() {
        addButton.click();
        return this;
    }

    public UserPage fillName(String name) {
        nameInput.enter(name);
        return this;
    }

    public UserPage clickSave() {
        saveButton.click();
        return this;
    }

    public UserPage shouldHaveRow(String text) {
        userTable.shouldContain(text);
        return this;
    }
}
