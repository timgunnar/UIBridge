package com.acme.components;

import org.openqa.selenium.WebDriver;
import org.openqa.selenium.WebElement;
import org.openqa.selenium.By;
import org.testng.Assert;

public class WebButton {
    private final WebDriver driver;
    private final String rootXpath;

    public WebButton(WebDriver driver, String moduleName) {
        this.driver = driver;
        this.rootXpath = "//button[@data-module='" + moduleName + "']";
    }

    public void click() {
        driver.findElement(By.xpath(rootXpath)).click();
    }

    public void assertEnabled() {
        Assert.assertTrue(driver.findElement(By.xpath(rootXpath)).isEnabled());
    }

    public void assertDisabled() {
        Assert.assertFalse(driver.findElement(By.xpath(rootXpath)).isEnabled());
    }
}
