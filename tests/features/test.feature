Feature: Test Admin UI Verification
    As an administrator
    I want to verify the Test admin UI module
    So that I can confirm the module loads correctly in the admin panel

    Background:
        Given the application is running
        And I navigate to the admin panel

    Scenario: Verify Test module loads in admin panel
        When I select the "Test" tab in the admin panel
        Then I should see "Test module active" in the admin content

    Scenario: Verify Test tab header
        Given I have selected the "Test" tab
        Then I should see "Test" in the header
