#!/bin/bash

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
TEST_ARGS=""
HEADED=false
INTERACTIVE=false
SERVICE="test"
COMPOSE_FILE="-f docker-compose.yml -f docker-compose.test.yml"

# Function to show help
show_help() {
    echo -e "${BLUE}Test Runner Script${NC}"
    echo "Usage: ./run_tests.sh [options] [pytest arguments]"
    echo ""
    echo "Options:"
    echo "  -h, --help              Show this help message"
    echo "  --headed                Run tests with browser visible (uses Xvfb)"
    echo "  -i, --interactive       Run in interactive mode (bash shell)"
    echo "  --debug                  Enable debug output (PYTEST_DEBUG=true)"
    echo "  --no-db-cleanup         Don't create/recreate test database"
    echo ""
    echo "Examples:"
    echo "  ./run_tests.sh                                   # Run all tests"
    echo "  ./run_tests.sh tests/step_defs/                  # Run BDD tests only"
    echo "  ./run_tests.sh -m 'not slow'                     # Skip slow tests"
    echo "  ./run_tests.sh --headed tests/step_defs/rag_steps.py  # Run RAG tests with browser"
    echo "  ./run_tests.sh -i                                # Get interactive shell"
    echo "  ./run_tests.sh --debug -v tests/ --pdb           # Debug mode with pdb"
    exit 0
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            show_help
            ;;
        --headed)
            HEADED=true
            SERVICE="test-headed"
            shift
            ;;
        -i|--interactive)
            INTERACTIVE=true
            shift
            ;;
        --debug)
            export PYTEST_DEBUG=true
            shift
            ;;
        --no-db-cleanup)
            NO_DB_CLEANUP=true
            shift
            ;;
        *)
            # Collect remaining arguments as pytest args
            TEST_ARGS="$TEST_ARGS $1"
            shift
            ;;
    esac
done

# Set default test args if none provided
if [ -z "$TEST_ARGS" ]; then
    TEST_ARGS="-v tests/"
fi

echo -e "${YELLOW}========================================${NC}"
echo -e "${YELLOW}Test Environment Setup${NC}"
echo -e "${YELLOW}========================================${NC}"
echo -e "Mode: ${GREEN}$([ "$HEADED" = true ] && echo "HEADED" || echo "HEADLESS")${NC}"
echo -e "Service: ${BLUE}$SERVICE${NC}"
echo -e "Test args: ${BLUE}$TEST_ARGS${NC}"
echo -e "Debug mode: ${BLUE}${PYTEST_DEBUG:-false}${NC}"
echo -e "${YELLOW}========================================${NC}\n"

# Create necessary directories
mkdir -p test_data test-reports tests/debug test-artifacts

# Set up test database (unless skipped)
if [ "$NO_DB_CLEANUP" != true ]; then
    echo -e "${YELLOW}Setting up test database...${NC}"
    # Drop and recreate test database to ensure clean state
    docker-compose $COMPOSE_FILE exec -T mysql mysql -u root -p${MYSQL_ROOT_PASSWORD} \
        -e "DROP DATABASE IF EXISTS ${MYSQL_DATABASE}_test;" 2>/dev/null
    docker-compose $COMPOSE_FILE exec -T mysql mysql -u root -p${MYSQL_ROOT_PASSWORD} \
        -e "CREATE DATABASE ${MYSQL_DATABASE}_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;" 2>/dev/null
    echo -e "${GREEN}✓ Test database ready${NC}\n"
fi

# Run tests
if [ "$INTERACTIVE" = true ]; then
    echo -e "${YELLOW}Starting interactive shell...${NC}"
    docker-compose $COMPOSE_FILE run --rm \
        -e PYTEST_DEBUG=${PYTEST_DEBUG:-false} \
        $SERVICE /bin/bash
else
    echo -e "${YELLOW}Running tests...${NC}"
    echo -e "Command: ${BLUE}pytest $TEST_ARGS${NC}\n"

    # Set environment variables for test run
    export PYTEST_DEBUG=${PYTEST_DEBUG:-false}

    # Run the tests
    docker-compose $COMPOSE_FILE run --rm \
        -e PYTEST_DEBUG \
        $SERVICE pytest $TEST_ARGS

    # Capture exit code
    EXIT_CODE=$?

    echo -e "\n${YELLOW}========================================${NC}"
    if [ $EXIT_CODE -eq 0 ]; then
        echo -e "${GREEN}✓ All tests passed!${NC}"
    else
        echo -e "${RED}✗ Tests failed with exit code $EXIT_CODE${NC}"
        echo -e "${YELLOW}Check test reports in ./test-reports/ and screenshots in ./tests/debug/${NC}"
    fi
    echo -e "${YELLOW}========================================${NC}"

    exit $EXIT_CODE
fi
