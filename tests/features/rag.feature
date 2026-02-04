Feature: RAG System Functionality
    As a user with RAG capabilities
    I want to verify that the RAG system correctly provides context to LLM responses
    So that I can ensure document-based question answering works properly

    Background:
        Given the application is running
        And the default user "System Administrator" is logged in
        And the mock LLM is configured and available

    Scenario: RAG enabled conversation
        When I navigate to the chat page
        And I create a new conversation named "RAG Enabled Test"
        Given I enable RAG context injection
        When I ask "Where does Kevin live?"
        Then I should see a RAG-enhanced response with address information

    Scenario: RAG disabled conversation
        When I navigate to the chat page
        And I create a new conversation named "RAG Disabled Test"
        Given I disable RAG context injection
        When I ask "Where does Kevin live?"
        Then I should see a generic response without address information
