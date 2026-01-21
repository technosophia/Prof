Feature: Main Page Button
    As a user of the multilingual application
    I want to click the main button
    So that I can see a success message

    Background:
        Given the application is running
        And the current language is "en"

    Scenario: Click the main button
        When I click the "button_text" button
        Then I should see the "button_clicked" message

    Scenario: Click button in French language
        Given the current language is "fr"
        When I click the "button_text" button
        Then I should see the "button_clicked" message in French
