package com.acme.tests;

import com.acme.pages.UserManagementPage;
import com.acme.data.UserTestData;
import org.testng.annotations.Test;
import org.testng.annotations.BeforeMethod;
import org.testng.Assert;
import org.openqa.selenium.WebDriver;
import org.openqa.selenium.chrome.ChromeDriver;

/**
 * 用户创建测试 — TestNG 风格。
 */
public class TestUserCreate {
    private WebDriver driver;
    private UserManagementPage userPage;

    @BeforeMethod
    public void setUp() {
        driver = new ChromeDriver();
        userPage = new UserManagementPage(driver);
        userPage.navigateTo();
    }

    @Test
    public void testCreateSingleUser() {
        userPage.addBtn.click();
        userPage.searchBox.enter(UserTestData.VALID_USER_NAME);
        userPage.searchBtn.click();
        userPage.userTable.waitForLoad(5);
        userPage.userTable.assertRowContains(UserTestData.VALID_USER_NAME);
    }

    @Test
    public void testSearchExistingUser() {
        userPage.searchBox.enter(UserTestData.EXISTING_USER_NAME);
        userPage.searchBtn.click();
        userPage.userTable.waitForLoad(5);
        Assert.assertEquals(userPage.userTable.getRowCount(), 1);
    }
}
