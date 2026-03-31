.PHONY: test test-all test-discover test-unit build check-compile docker-build docker-build-no-cache help clean

# Default target
help:
	@echo "Available targets:"
	@echo "  make test                - Run full unittest discovery"
	@echo "  make test-all            - Run all tests (alias for test)"
	@echo "  make test-discover       - Run full unittest discovery"
	@echo "  make test-unit           - Run unittest discovery (verbose)"
	@echo "  make build               - Run Python compile checks"
	@echo "  make check-compile       - Byte-compile Python files (syntax check)"
	@echo "  make docker-build        - Build Docker image"
	@echo "  make docker-build-no-cache - Build Docker image without cache"
	@echo "  make clean               - Clean Python cache files"
	@echo "  make help                - Show this help message"

# Build target for compile-time validation
build: check-compile
	@echo ""
	@echo "=========================================="
	@echo "Build checks completed!"
	@echo "=========================================="

# Python compile check (catches syntax/compile-time errors)
check-compile:
	@echo "Running Python compile checks..."
	@uv run python -m compileall -q jmcp.py jmcp_token_manager.py utils tests


# Run full unittest discovery
test: test-discover
	@echo ""
	@echo "=========================================="
	@echo "All tests completed!"
	@echo "=========================================="

# Explicit alias for full discovery
test-discover:
	@echo "Running full unittest discovery..."
	@uv run python -m unittest discover -s tests -v

# Backward-compatible alias
test-unit: test-discover


# Alias for test
test-all: test
	@echo ""
	@echo "=========================================="
	@echo "All tests completed!"
	@echo "=========================================="

# Build Docker image
docker-build:
	@echo "Building Docker image..."
	docker build -t junos-mcp-server:latest .
	@echo "Docker image built successfully: junos-mcp-server:latest"

# Build Docker image without cache
docker-build-no-cache:
	@echo "Building Docker image without cache..."
	docker build --no-cache -t junos-mcp-server:latest .
	@echo "Docker image built successfully (no-cache): junos-mcp-server:latest"

# Clean Python cache files
clean:
	@echo "Cleaning Python cache files..."
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete
	@find . -type f -name "*.pyo" -delete
	@find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	@echo "Clean complete!"
