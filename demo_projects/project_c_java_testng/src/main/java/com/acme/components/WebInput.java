package com.acme.components;

import org.openqa.selenium.WebDriver;
import org.openqa.selenium.WebElement;
import org.openqa.selenium.By;
import org.testng.Assert;

/**
 * WebInput — 输入框组件封装。
 */
public class WebInput {
    private final WebDriver driver;
    private final String rootXpath;

    public WebInput(WebDriver driver, String moduleName) {
        this.driver = driver;
        this.rootXpath = "//input[@data-module='" + moduleName + "']";
    }

    public void enter(String text) {
        WebElement input = driver.findElement(By.xpath(rootXpath));
        input.clear();
        input.sendKeys(text);
    }

    public void clear() {
        driver.findElement(By.xpath(rootXpath)).clear();
    }

    public String getValue() {
        return driver.findElement(By.xpath(rootXpath)).getAttribute("value");
    }

    public void assertValue(String expected) {
        Assert.assertEquals(getValue(), expected);
    }
}
