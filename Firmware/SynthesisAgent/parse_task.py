import json
import argparse

def pretty_print(data, max_depth, show_params, current_depth=0, indent="  "):
    """
    Recursively prints nested dictionaries and lists with controlled depth.
    """
    if current_depth >= max_depth:
        if isinstance(data, dict):
            print(f"{indent}{{...}}")
        elif isinstance(data, list):
            print(f"{indent}[...]")
        else:
            print(f"{indent}{data}")
        return

    if isinstance(data, dict):
        for key, value in data.items():
            if key == 'actionParams' and not show_params:
                print(f"{indent}{key}: [hidden, use --show-params to display]")
                continue

            if isinstance(value, (dict, list)):
                print(f"{indent}{key}:")
                pretty_print(value, max_depth, show_params, current_depth + 1, indent + "  ")
            else:
                print(f"{indent}{key}: {value}")
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, (dict, list)):
                pretty_print(item, max_depth, show_params, current_depth + 1, indent + "  ")
            else:
                print(f"{indent}- {item}")

def parse_task_flow(file_path: str, args):
    """
    Loads and parses a complex task JSON, printing a summary based on arguments.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            task_data = json.load(f)
    except FileNotFoundError:
        print(f"Error: The file '{file_path}' was not found.")
        return
    except json.JSONDecodeError:
        print(f"Error: The file '{file_path}' is not a valid JSON file.")
        return

    print(f"--- Parsing Task (max_depth={args.max_depth}, show_params={args.show_params}, ignore_nodes={args.ignore_nodes}) ---")

    basic_info = task_data.get('basic', {})
    task_name = basic_info.get('taskName', 'N/A')
    print(f"Task Name: {task_name}\n")

    nodes = {}
    edges = []
    
    # In this new structure, the actual step data is in a separate list `dataList`
    # and referenced by `dataId` in the node. Let's create a map for it.
    data_map = {item['dataId']: item for item in task_data.get('dataList', [])}

    for item in task_data.get('flowChartList', []):
        if item.get('component') == 'node':
            node_id = item.get('id')
            data_id = item.get('data', {}).get('dataId')
            # Combine the node's visual data with its step data
            if data_id in data_map:
                nodes[node_id] = data_map[data_id]
                # Also add the human-readable name from the visual node
                nodes[node_id]['name'] = item.get('data', {}).get('name')
        elif item.get('shape') == 'edge':
            edges.append(item)

    if not nodes or not edges:
        print("Could not find a valid workflow structure.")
        return

    start_node_id = None
    for node_id, node_data in nodes.items():
        if node_data.get('workstationType') == 'start':
            start_node_id = node_id
            break

    if not start_node_id:
        print("Could not determine the workflow start point.")
        return

    print("Workflow Sequence:")
    edge_map = {edge['source']['cell']: edge['target']['cell'] for edge in edges}
    current_node_id = start_node_id
    step_count = 1

    ignore_list = [name.strip() for name in args.ignore_nodes.split(',') if name.strip()]

    for _ in range(len(nodes) + 1):
        node_data = nodes.get(current_node_id)
        if not node_data:
            break

        node_type = node_data.get('workstationType', 'N/A')
        node_name = node_data.get('name', 'N/A')
        
        # Skip start/end and ignored nodes
        if node_type not in ['start', 'end'] and node_name not in ignore_list:
            print(f"\n  Step {step_count}: '{node_name}' (Type: {node_type})")
            print("  ---------------------------------")
            pretty_print(node_data, args.max_depth, args.show_params)
            step_count += 1

        if current_node_id in edge_map:
            current_node_id = edge_map[current_node_id]
        else:
            break

    print("\n--- End of Analysis ---")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Parse and summarize a complex task JSON file.")
    parser.add_argument(
        '--max-depth',
        type=int,
        default=1,
        help="Maximum depth to expand nested JSON objects. Default: 1"
    )
    parser.add_argument(
        '--show-params',
        action='store_true',
        help="If set, shows the detailed 'actionParams' for each step."
    )
    parser.add_argument(
        '--ignore-nodes',
        type=str,
        default="",
        help="Comma-separated list of node names to ignore in the output."
    )
    args = parser.parse_args()
    
    parse_task_flow('task.json', args)