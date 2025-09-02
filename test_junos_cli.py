#!/usr/bin/env python3
"""
Test script for _run_junos_cli_command() function
This allows testing Junos commands without setting up the full MCP server
"""

import sys
import json
import logging

# Import the functions directly from jmcp
import jmcp

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger('test-junos-cli')


def load_devices(devices_file: str) -> bool:
    """Load devices configuration from JSON file"""
    try:
        with open(devices_file, 'r') as f:
            jmcp.devices = json.load(f)
            log.info(f"Loaded {len(jmcp.devices)} device(s) from {devices_file}")
            for name in jmcp.devices.keys():
                log.info(f"  - {name}")
            return True
    except FileNotFoundError:
        log.error(f"Device file not found: {devices_file}")
        return False
    except json.JSONDecodeError as e:
        log.error(f"Invalid JSON in device file: {e}")
        return False
    except Exception as e:
        log.error(f"Error loading device file: {e}")
        return False


def interactive_mode():
    """Interactive mode for testing commands"""
    print("\n=== Interactive Mode ===")
    print("Type 'help' for available commands")
    print("Type 'quit' or 'exit' to leave\n")
    
    while True:
        try:
            user_input = input("junos-test> ").strip()
            
            if not user_input:
                continue
                
            if user_input.lower() in ['quit', 'exit']:
                print("Goodbye!")
                break
                
            if user_input.lower() == 'help':
                print("\nAvailable commands:")
                print("  list                - List all configured routers")
                print("  test <router>       - Test connection to a router")
                print("  exec <router> <cmd> - Execute command on router")
                print("  help                - Show this help")
                print("  quit/exit           - Exit the program\n")
                continue
                
            if user_input.lower() == 'list':
                if not jmcp.devices:
                    print("No devices loaded")
                else:
                    print("\nConfigured routers:")
                    for name, info in jmcp.devices.items():
                        print(f"  - {name} ({info['ip']}:{info.get('port', 22)})")
                print()
                continue
                
            parts = user_input.split(None, 2)
            
            if parts[0].lower() == 'test' and len(parts) >= 2:
                router = parts[1]
                print(f"Testing connection to {router}...")
                result = jmcp._run_junos_cli_command(router, "show version | match Hostname", timeout=30)
                print(result)
                continue
                
            if parts[0].lower() == 'exec' and len(parts) >= 3:
                router = parts[1]
                command = parts[2]
                print(f"Executing on {router}: {command}")
                result = jmcp._run_junos_cli_command(router, command)
                print("\nResult:")
                print(result)
                continue
                
            print(f"Unknown command: {user_input}")
            print("Type 'help' for available commands")
            
        except KeyboardInterrupt:
            print("\nUse 'quit' or 'exit' to leave")
            continue
        except Exception as e:
            log.error(f"Error: {e}")


def main():
    """Main function for testing _run_junos_cli_command"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Test Junos CLI commands without MCP server',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive mode
  %(prog)s -f devices.json
  
  # Execute a single command
  %(prog)s -f devices.json -r router1 -c "show version"
  
  # Test connection to all devices
  %(prog)s -f devices.json --test-all
  
  # Increase verbosity for debugging
  %(prog)s -f devices.json -v -r router1 -c "show interfaces terse"
        """
    )
    
    parser.add_argument(
        '-f', '--file',
        required=True,
        help='Path to devices JSON file'
    )
    
    parser.add_argument(
        '-r', '--router',
        help='Router name to connect to'
    )
    
    parser.add_argument(
        '-c', '--command',
        help='Command to execute on the router'
    )
    
    parser.add_argument(
        '-t', '--timeout',
        type=int,
        default=360,
        help='Command timeout in seconds (default: 360)'
    )
    
    parser.add_argument(
        '--test-all',
        action='store_true',
        help='Test connection to all configured devices'
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    
    parser.add_argument(
        '--format',
        choices=['json', 'text'],
        default='text',
        help='Output format for command results'
    )
    
    args = parser.parse_args()
    
    # Set logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        jmcp.log.setLevel(logging.DEBUG)
        log.setLevel(logging.DEBUG)
    
    # Load devices
    if not load_devices(args.file):
        sys.exit(1)
    
    # Test all devices mode
    if args.test_all:
        print("\nTesting all devices...")
        for router_name in jmcp.devices.keys():
            print(f"\n--- Testing {router_name} ---")
            result = jmcp._run_junos_cli_command(
                router_name, 
                "show version | match Hostname", 
                timeout=30
            )
            print(result)
        sys.exit(0)
    
    # Single command mode
    if args.router and args.command:
        print(f"\nExecuting command on {args.router}...")
        result = jmcp._run_junos_cli_command(
            args.router,
            args.command,
            format=args.format,
            timeout=args.timeout
        )
        print("\nResult:")
        print(result)
        sys.exit(0)
    
    # Interactive mode
    if not args.router and not args.command:
        interactive_mode()
        sys.exit(0)
    
    # Invalid arguments
    parser.error("Please specify both --router and --command, or use interactive mode")


if __name__ == '__main__':
    main()