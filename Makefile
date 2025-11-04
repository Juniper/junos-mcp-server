.PHONY: test test-all test-config test-router-list docker-build help clean

# Default target
help:
	@echo "Available targets:"
	@echo "  make test              - Run all tests"
	@echo "  make test-all          - Run all tests (alias for test)"
	@echo "  make test-config       - Run config validation tests"
	@echo "  make test-router-list  - Run get_router_list tests"
	@echo "  make docker-build      - Build Docker image"
	@echo "  make clean             - Clean Python cache files"
	@echo "  make help              - Show this help message"

# Run all tests
test: test-config test-router-list
	@echo ""
	@echo "=========================================="
	@echo "All tests completed!"
	@echo "=========================================="

# Alias for test
test-all: test

# Run config validation tests
test-config:
	@echo "Running config validation tests..."
	@uv run python test_config_validation.py

# Run get_router_list tests
test-router-list:
	@echo "Running get_router_list tests..."
	@uv run python test_get_router_list.py

# Build Docker image
docker-build:
	@echo "Building Docker image..."
	docker build -t junos-mcp-server:latest .
	@echo "Docker image built successfully: junos-mcp-server:latest"

# Clean Python cache files
clean:
	@echo "Cleaning Python cache files..."
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete
	@find . -type f -name "*.pyo" -delete
	@find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	@echo "Clean complete!"
