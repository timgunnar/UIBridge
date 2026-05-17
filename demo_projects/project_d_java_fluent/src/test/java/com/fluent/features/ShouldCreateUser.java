package com.fluent.features;

import com.fluent.pages.UserPage;
import com.fluent.builders.UserBuilder;
import org.testng.annotations.Test;
import org.testng.annotations.BeforeMethod;
import org.openqa.selenium.WebDriver;
import org.openqa.selenium.chrome.ChromeDriver;
import static org.assertj.core.api.Assertions.assertThat;

/**
 * 用户创建特性 — Fluent + AssertJ 风格。
 * BDD 命名: ShouldXxx
 */
public class ShouldCreateUser {
    private WebDriver driver;
    private UserPage userPage;

    @BeforeMethod
    public void setUp() {
        driver = new ChromeDriver();
        userPage = new UserPage(driver);
    }

    @Test
    public void shouldCreateSingleUser() {
        UserBuilder data = new UserBuilder()
            .withName("张三")
            .withAge("25")
            .build();

        userPage.navigateTo("https://example.com/user/manage")
                .clickAdd()
                .fillName(data.getName())
                .clickSave()
                .shouldHaveRow(data.getName());
    }

    @Test
    public void shouldSearchExistingUser() {
        UserBuilder data = new UserBuilder()
            .withName("李四")
            .build();

        userPage.navigateTo("https://example.com/user/manage")
                .searchFor(data.getName())
                .shouldHaveRow(data.getName());
    }
}
