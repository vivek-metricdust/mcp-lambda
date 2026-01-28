import json
import os
import urllib.request
import urllib.parse
import logging

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# --- Configuration (Populated from Environment Variables) ---
API_BASE_URL = "https://mz5wkrw9e4.execute-api.us-east-1.amazonaws.com/property_listing_service/prod/public"
TENANT = os.environ.get("TENANT", "shopprop")
API_KEY = os.environ.get("API_KEY", "59d02ffe-07c6-4823-99bd-f003fe5119de")


def create_mcp_response(request_id, result):
    """Create a standard MCP JSON-RPC response"""
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def create_error_response(request_id, code, message):
    """Create a standard MCP error response"""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def handle_initialize(params):
    """Handle MCP initialize request"""
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "property-search-mcp-server", "version": "1.0.0"},
    }


def handle_tools_list():
    """Return list of available tools"""
    return {
        "tools": [
            {
                "name": "search_properties",
                "description": "Search for properties for sale in a specific city and state. Returns property listings with details like price, bedrooms, bathrooms, area, and images.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "city": {
                            "type": "string",
                            "description": "City name (e.g., 'Phoenix', 'Los Angeles')",
                        },
                        "state": {
                            "type": "string",
                            "description": "State code (e.g., 'AZ', 'CA')",
                        },
                        "min_price": {
                            "type": "integer",
                            "description": "Minimum price in USD (optional)",
                        },
                        "max_price": {
                            "type": "integer",
                            "description": "Maximum price in USD (optional)",
                        },
                        "bedrooms": {
                            "type": "integer",
                            "description": "Minimum number of bedrooms (optional)",
                        },
                        "bathrooms": {
                            "type": "integer",
                            "description": "Minimum number of bathrooms (optional)",
                        },
                        "size": {
                            "type": "integer",
                            "description": "Number of results to return (default: 10, max: 50)",
                            "default": 10,
                        },
                        "cursor": {
                            "type": "string",
                            "description": "Pagination cursor for next page of results (optional)",
                        },
                    },
                    "required": ["city", "state"],
                },
            }
        ]
    }


def search_properties_api(params):
    """Execute property search against the external API"""

    # Check for API Key
    if not API_KEY:
        return {
            "success": False,
            "error": "API_KEY environment variable not set on Lambda.",
        }

    city = params.get("city")
    state = params.get("state")

    if not city or not state:
        return {
            "success": False,
            "error": "Missing required parameters: 'city' and 'state' are required.",
        }

    try:
        # Construct URL
        api_path = f"/tenant/{TENANT}/city/{city.lower()}/state/{state.lower()}"
        full_url = f"{API_BASE_URL}{api_path}"

        # Prepare Headers
        headers = {
            "apikey": API_KEY,
            "company": TENANT,
            "tenant": TENANT,
            "Content-Type": "application/json",
            "user": "mcp-lambda-user",
        }

        # Prepare Payload
        payload = {
            "sort_by": "last_updated_time",
            "order_by": "desc",
            "searched_address_formatted": f"{city}, {state}, USA",
            "property_status": "SALE",
            "output": [
                "area",
                "price",
                "bedroom",
                "bathroom",
                "property_descriptor",
                "location",
                "address",
                "image_url",
                "last_updated_time",
            ],
            "image_count": 10,
            "size": int(params.get("size", 10)),
            "allowed_mls": [
                "ARMLS",
                "ACTRISMLS",
                "BAREISMLS",
                "CRMLS",
                "CENTRALMLS",
                "MLSLISTINGS",
                "NWMLS",
                "NTREISMLS",
                "shopprop",
            ],
        }

        # Add optional filters
        if "min_price" in params:
            payload["min_price"] = int(params["min_price"])
        if "max_price" in params:
            payload["max_price"] = int(params["max_price"])
        if "bedrooms" in params:
            payload["bedroom"] = int(params["bedrooms"])
        if "bathrooms" in params:
            payload["bathroom"] = int(params["bathrooms"])
        if "cursor" in params:
            payload["cursor"] = params["cursor"]

        # Execute HTTP Post
        req = urllib.request.Request(
            full_url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=25) as response:
            response_body = response.read().decode("utf-8")
            data = json.loads(response_body)

            return {
                "success": True,
                "data": data.get("data", []),
                "cursor": data.get("cursor"),
                "count": len(data.get("data", [])),
            }

    except urllib.error.HTTPError as e:
        error_msg = e.read().decode("utf-8")
        logger.error(f"API Error: {e.code} - {error_msg}")
        return {"success": False, "error": f"API Error ({e.code}): {error_msg}"}
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return {"success": False, "error": f"Internal Error: {str(e)}"}


def format_property_results(result):
    """Format property search results for MCP response in markdown format"""

    if not result.get("success"):
        error_msg = result.get("error", "Unknown error occurred")
        return [{"type": "text", "text": f"Error: {error_msg}"}]

    properties = result.get("data", [])
    cursor = result.get("cursor")

    # Ensure properties is a list
    if not properties or not isinstance(properties, list):
        properties = []

    if len(properties) == 0:
        return [
            {
                "type": "text",
                "text": "No properties found matching your search criteria.",
            }
        ]

    # Format the results
    result_string = f"Found {len(properties)} properties:\n\n"
    result_json = []

    for prop in properties:
        # Safely get nested values
        address_obj = prop.get("address", {})
        price_obj = prop.get("price", {})
        area_obj = prop.get("area", {})
        bedroom_obj = prop.get("bedroom", {})
        bathroom_obj = prop.get("bathroom", {})
        property_descriptor = prop.get("property_descriptor", {})
        images_list = prop.get("image_url", []) or prop.get("image_urls", [])

        # Extract values
        full_address = address_obj.get("full_address", "N/A") if address_obj else "N/A"
        google_address = (
            address_obj.get("google_address", "N/A") if address_obj else "N/A"
        )

        # Combine addresses for display
        display_address = f"{full_address} | {google_address}"

        price_val = price_obj.get("current") if price_obj else None
        formatted_price = (
            f"${price_val:,}" if isinstance(price_val, (int, float)) else "N/A"
        )

        bedrooms = bedroom_obj.get("count", "N/A") if bedroom_obj else "N/A"
        bathrooms = bathroom_obj.get("count", "N/A") if bathroom_obj else "N/A"

        area_val = area_obj.get("finished") if area_obj else None
        formatted_area = (
            f"{area_val:,}" if isinstance(area_val, (int, float)) else "N/A"
        )

        # MLS Info
        mls_name = property_descriptor.get("mls_name", "N/A")
        mls_id = property_descriptor.get("id", "N/A")
        mls_info = f"{mls_name}_{mls_id}"

        # Images (First 5)
        image_urls = images_list[:5] if isinstance(images_list, list) else []

        result_string += (
            f"- **{display_address}**\n"
            f"  - Price: {formatted_price}\n"
            f"  - Beds: {bedrooms} | Baths: {bathrooms}\n"
            f"  - Area: {formatted_area} sqft\n"
            f"  - MLS: {mls_info}\n"
            f"  - Images: {', '.join(image_urls)}\n\n"
        )

        result_json.append(
            {
                "full_address": full_address,
                "google_address": google_address,
                "price": formatted_price,
                "bedrooms": bedrooms,
                "bathrooms": bathrooms,
                "area": formatted_area,
                "mls_info": mls_info,
                "image_urls": image_urls,
            }
        )

    # Add pagination info
    if cursor:
        result_string += (
            f"\nMore results available. Use cursor: `{cursor}` for next page."
        )

    # Toggle between String and JSON output as required
    use_json_output = os.environ.get("OUTPUT_FORMAT", "string") == "json"

    if use_json_output:
        return [{"type": "text", "text": json.dumps(result_json, indent=2)}]

    return [{"type": "text", "text": result_string}]


def handle_tool_call(tool_name, arguments):
    """Execute the requested tool"""

    if tool_name == "search_properties":
        result = search_properties_api(arguments)
        return format_property_results(result)
    else:
        return [{"type": "text", "text": f"Unknown tool: {tool_name}"}]


def lambda_handler(event, context):
    """
    Main Lambda handler for MCP server
    Handles HTTP requests from Claude Desktop/Cursor
    """

    logger.info(f"Received event: {json.dumps(event)}")

    try:
        # Parse the request body
        if isinstance(event.get("body"), str):
            body = json.loads(event["body"])
        else:
            body = event.get("body", {})

        # Extract JSON-RPC fields
        method = body.get("method")
        params = body.get("params", {})
        request_id = body.get("id", 1)

        # Route to appropriate handler
        if method == "initialize":
            result = handle_initialize(params)
            response_body = create_mcp_response(request_id, result)

        elif method == "tools/list":
            result = handle_tools_list()
            response_body = create_mcp_response(request_id, result)

        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            content = handle_tool_call(tool_name, arguments)
            response_body = create_mcp_response(request_id, {"content": content})

        else:
            response_body = create_error_response(
                request_id, -32601, f"Method not found: {method}"
            )

        # Return HTTP response
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type",
                "Access-Control-Allow-Methods": "POST, OPTIONS",
            },
            "body": json.dumps(response_body),
        }

    except Exception as e:
        logger.error(f"Lambda handler error: {str(e)}")
        error_response = create_error_response(
            body.get("id", 1) if "body" in locals() else 1,
            -32603,
            f"Internal error: {str(e)}",
        )
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps(error_response),
        }
