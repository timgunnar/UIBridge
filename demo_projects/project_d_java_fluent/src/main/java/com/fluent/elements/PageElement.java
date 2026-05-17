package com.fluent.elements;

import org.openqa.selenium.WebDriver;
import org.openqa.selenium.WebElement;
import org.openqa.selenium.support.FindBy;
import org.openqa.selenium.support.PageFactory;
import static org.assertj.core.api.Assertions.assertThat;

/**
 * PageElement — 通用页面元素，支持链式调用。
 * 所有组件统一为此类型。
 */
public class PageElement {
    private final WebDriver driver;

    @FindBy(xpath = "")
    private WebElement element;

    private final String locator;

    public PageElement(WebDriver driver, String locator) {
        this.driver = driver;
        this.locator = locator;
        PageFactory.initElements(driver, this);
        this.element = driver.findElement(org.openqa.selenium.By.xpath(locator));
    }

    public PageElement click() {
        element.click();
        return this;
    }

    public PageElement enter(String text) {
        element.clear();
        element.sendKeys(text);
        return this;
    }

    public String getText() {
        return element.getText();
    }

    public PageElement shouldBeVisible() {
        assertThat(element.isDisplayed()).isTrue();
        return this;
    }

    public PageElement shouldContain(String text) {
        assertThat(element.getText()).contains(text);
        return this;
    }
}
