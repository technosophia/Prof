Feature: Conversation with LLM
    As a user of the conversation application
    I want to create a conversation and interact with a mock LLM
    So that I can validate the complete chat interface functionality

    Background:
        Given the application is running
        And the default user "Test User 1" is logged in
        And the mock LLM is configured and available

    Scenario: Create conversation and send a message
        When I navigate to the chat page
        And I create a new conversation named "First conversation"
        And I debug the current state
        And I send the message "Hello, can you say CODE to me?"
        And I debug the current state
        Then I should see a response from the mock LLM
        And I should see a response containing "CODE"

    Scenario: Conversation with multiple messages
        Given I have a conversation "Test exchange"
        When I send the message "What is your name?"
        Then I should see a response containing "Mock"
        When I send the message "Can you describe yourself?"
        Then I should see a response containing "test"

    Scenario: Regenerate last response
        Given I have a conversation with an assistant message
        When I click the regenerate button
        Then the last response should be updated

    Scenario: Switch between conversations
        Given I have two conversations: "Work" and "Personal"
        When I select the conversation "Work"
        Then I should see the history of "Work"
        When I select the conversation "Personal"
        Then I should see the history of "Personal"

    Scenario: Clear conversation messages
        Given I have a conversation "Temporary chat" with messages
        When I clear the conversation messages
        Then the conversation should be empty

    Scenario: Edit conversation title
        Given I have a conversation "Old title"
        When I edit the conversation title to "New title"
        Then I should see the conversation with title "New title"
