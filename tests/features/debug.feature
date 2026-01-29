Feature: Debug Admin UI Testing
    As an administrator
    I want to test the debug admin UI functionality
    So that I can validate the basic text input and display features work correctly

    Background:
        Given the application is running
        And I am logged in as an admin user
        And I navigate to the admin panel
        And the debug module is loaded
        And I select the "Debug" tab

    Scenario: Verify Debug tab loads correctly
        Then I should see "Debug and Testing" in the header

    Scenario: Text input and display
        When I enter text "Hello, Debug Admin!" in the text area
        And I click the "Display Text" button
        Then I should see "Hello, Debug Admin!" in the result section
        And I should see the character count displayed
        And I should see the word count displayed

    Scenario: Clear text functionality
        When I enter text "Test text to clear" in the text area
        And I click the "Display Text" button
        When I click the "Clear Text" button
        Then the result section should be empty

    Scenario: Test with empty text
        When I clear the text area
        And I click the "Display Text" button without entering text
        Then I should see a warning message about empty text
