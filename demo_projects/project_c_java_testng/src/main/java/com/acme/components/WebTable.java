package com.acme.components;

import org.openqa.selenium.WebDriver;
import org.openqa.selenium.WebElement;
import org.openqa.selenium.By;
import org.testng.Assert;

/**
 * WebTable — 表格组件封装。
 * 基于 data-module 属性定位。
 */
public class WebTable {
    private final WebDriver driver;
    private final String rootXpath;

    public WebTable(WebDriver driver, String moduleName) {
        this.driver = driver;
        this.rootXpath = "//div[@data-module='" + moduleName + "']";
    }

    public void waitForLoad(int timeout) {
        driver.findElement(By.xpath(rootXpath + "//tr")).isDisplayed();
    }

    public int getRowCount() {
        return driver.findElements(By.xpath(rootXpath + "//tr")).size();
    }

    public void clickRow(int index) {
        driver.findElement(By.xpath(rootXpath + "//tr[" + index + "]")).click();
    }

    public String getCellText(int row, int col) {
        return driver.findElement(By.xpath(rootXpath + "//tr[" + row + "]/td[" + col + "]")).getText();
    }

    public void assertRowContains(String text) {
        WebElement row = driver.findElement(By.xpath(rootXpath + "//tr[contains(., '" + text + "')]"));
        Assert.assertTrue(row.isDisplayed(), "Row containing '" + text + "' should be visible");
    }

    public void filterByColumn(int col, String value) {
        WebElement filter = driver.findElement(
            By.xpath(rootXpath + "//thead//th[" + col + "]//input")
        );
        filter.sendKeys(value);
    }
}
