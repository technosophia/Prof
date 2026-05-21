Feature: Permission enforcement
  Non-regression tests for role-based access control in the admin panel.
  These scenarios document the current permission behaviour.
  They must pass before and after any refactoring of the permission layer.

  Background:
    Given the application is running

  # ---------------------------------------------------------------------------
  # Tab visibility — admin-only tabs (sub-tabs inside the Users module tab)
  # ---------------------------------------------------------------------------

  Scenario: Admin sees Import/Export and Email Templates tabs
    Given the default user "System Administrator" is logged in
    And I navigate to the admin panel
    And I select the "Users" tab
    Then I should see the tab "Import/Export"
    And I should see the tab "Email Templates"

  Scenario: Master does not see admin-only tabs
    Given the default user "Master User 1" is logged in
    And I navigate to the admin panel
    And I select the "Users" tab
    Then I should not see the tab "Import/Export"
    And I should not see the tab "Email Templates"

  # ---------------------------------------------------------------------------
  # Delete button — self-delete is always blocked
  # ---------------------------------------------------------------------------

  Scenario: Admin cannot delete themselves
    Given the default user "System Administrator" is logged in
    And I navigate to the admin panel
    And I select the "Users" tab
    Then the delete button for user "System Administrator" should be disabled

  # ---------------------------------------------------------------------------
  # User list scope — master sees only their own users
  # ---------------------------------------------------------------------------

  Scenario: Master sees their own normal users in the list
    Given the default user "Master User 1" is logged in
    And I navigate to the admin panel
    And I select the "Users" tab
    Then I should see "Normal User 1 (Master 1)" in the result section

  Scenario: Master does not see the admin user in their user management list
    Given the default user "Master User 1" is logged in
    And I navigate to the admin panel
    And I select the "Users" tab
    Then I should not see "System Administrator" in the user management list

  # ---------------------------------------------------------------------------
  # Normal user cannot access user administration
  # ---------------------------------------------------------------------------

  Scenario: Normal user cannot access user administration
    Given the default user "Normal User 1 (Master 1)" is logged in
    Then the admin panel button should be disabled
