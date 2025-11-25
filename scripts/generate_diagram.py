import os
import ast
import re
import json
from pathlib import Path

# Configuration
ROOT_DIR = os.getcwd()
DIRS_TO_SCAN = [
    os.path.join(ROOT_DIR, "backend"),
    os.path.join(ROOT_DIR, "core"),
    os.path.join(ROOT_DIR, "frontend", "src"),
]
OUTPUT_FILE = "codebase_architecture.html"

def get_module_group(path):
    if "backend" in path: return "backend"
    if "core" in path: return "core"
    if "frontend" in path: return "frontend"
    return "default"

def parse_python_imports(file_path):
    imports = set()
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.split('.')[0])
    except Exception:
        pass
    return imports

def parse_ts_imports(file_path):
    imports = set()
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        matches = re.findall(r"from\s+['\"]([^'\"]+)['\"]", content)
        for match in matches:
            if match.startswith("."):
                imports.add(match)
            else:
                imports.add(match.split('/')[0])
    except Exception:
        pass
    return imports

def get_module_name(rel_path):
    dirname = os.path.dirname(rel_path)
    if not dirname:
        return "root"
    return dirname.replace("\\", "/")

def generate_interactive_diagram():
    modules = {} # module_path -> set of dependencies
    module_files = {} # module_path -> list of files
    
    print("Scanning files...")
    
    file_to_module = {}
    total_files = 0
    
    for root_path in DIRS_TO_SCAN:
        for root, _, files in os.walk(root_path):
            if "node_modules" in root or "__pycache__" in root or "dist" in root:
                continue
                
            for file in files:
                if not file.endswith(('.py', '.ts', '.tsx', '.js', '.jsx')):
                    continue
                    
                total_files += 1
                abs_path = os.path.join(root, file)
                rel_path = os.path.relpath(abs_path, ROOT_DIR).replace("\\", "/")
                module_name = get_module_name(rel_path)
                
                file_to_module[rel_path] = module_name
                if module_name not in modules:
                    modules[module_name] = set()
                
                if module_name not in module_files:
                    module_files[module_name] = []
                module_files[module_name].append(rel_path)

    print("Analyzing imports...")
    for rel_path, source_module in file_to_module.items():
        abs_path = os.path.join(ROOT_DIR, rel_path)
        
        current_imports = set()
        if rel_path.endswith('.py'):
            current_imports = parse_python_imports(abs_path)
        else:
            current_imports = parse_ts_imports(abs_path)
            
        for imp in current_imports:
            target_module = None
            
            if imp.startswith("."):
                base_dir = os.path.dirname(rel_path)
                resolved = os.path.normpath(os.path.join(base_dir, imp)).replace("\\", "/")
                for known_file in file_to_module:
                    if known_file.startswith(resolved):
                        target_module = file_to_module[known_file]
                        break
            
            if not target_module:
                imp_path = imp.replace(".", "/")
                for known_file in file_to_module:
                    if known_file.endswith(imp_path + ".py") or known_file.endswith(imp_path + "/__init__.py"):
                        target_module = file_to_module[known_file]
                        break
                        
            if target_module and target_module != source_module:
                modules[source_module].add(target_module)

    # Build JSON data for vis-network
    nodes = []
    edges = []
    
    module_ids = {mod: i for i, mod in enumerate(modules.keys())}
    
    for mod, mod_id in module_ids.items():
        group = get_module_group(mod)
        file_count = len(module_files.get(mod, []))
        
        files_list = "<br>".join(module_files.get(mod, [])[:10])
        if file_count > 10:
            files_list += f"<br>...and {file_count - 10} more"
            
        nodes.append({
            "id": mod_id,
            "label": os.path.basename(mod),
            "title": f"<b>{mod}</b><br>Files: {file_count}<br><br>{files_list}",
            "group": group,
            "value": file_count
        })
        
    for source, targets in modules.items():
        source_id = module_ids[source]
        for target in targets:
            if target in module_ids:
                target_id = module_ids[target]
                edges.append({
                    "from": source_id,
                    "to": target_id,
                    "arrows": "to"
                })

    graph_data = {
        "nodes": nodes,
        "edges": edges
    }
    
    stats = {
        "modules": len(modules),
        "files": total_files,
        "edges": len(edges)
    }
    
    # HTML Template with Refinements
    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Interactive Codebase Architecture</title>
    <script type="text/javascript" src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
    <link href="https://fonts.googleapis.com/icon?family=Material+Icons" rel="stylesheet">
    <style type="text/css">
        :root {{
            --bg-color: #f0f2f5;
            --text-color: #333;
            --panel-bg: rgba(255, 255, 255, 0.95);
            --panel-shadow: 0 4px 12px rgba(0,0,0,0.15);
            --border-color: #ddd;
            --btn-bg: #007bff;
            --btn-hover: #0056b3;
            --btn-text: white;
        }}
        
        /* Obsidian-like Dark Mode */
        body.dark-mode {{
            --bg-color: #1e1e1e;
            --text-color: #dcddde;
            --panel-bg: rgba(37, 37, 37, 0.95);
            --panel-shadow: 0 4px 12px rgba(0,0,0,0.5);
            --border-color: #444;
            --btn-bg: #7b68ee;
            --btn-hover: #6a5acd;
        }}

        body, html {{
            height: 100%;
            margin: 0;
            font-family: 'Inter', 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-color);
            overflow: hidden;
            transition: background-color 0.3s, color 0.3s;
        }}
        #mynetwork {{
            width: 100%;
            height: 100%;
            border: none;
        }}
        .panel {{
            position: absolute;
            background: var(--panel-bg);
            padding: 15px;
            border-radius: 8px;
            box-shadow: var(--panel-shadow);
            z-index: 10;
            transition: background 0.3s, box-shadow 0.3s;
            border: 1px solid var(--border-color);
        }}
        #controls {{
            top: 20px;
            left: 20px;
            width: 280px;
        }}
        #info-panel {{
            bottom: 20px;
            right: 20px;
            max-width: 300px;
            display: none;
        }}
        h2, h3 {{ margin-top: 0; font-size: 18px; font-weight: 600; }}
        h3 {{ font-size: 16px; border-bottom: 1px solid var(--border-color); padding-bottom: 8px; }}
        
        /* Legend Grid Layout */
        .legend-grid {{
            display: grid;
            grid-template-columns: auto auto 1fr;
            gap: 8px 12px;
            align-items: center;
            margin-bottom: 15px;
            font-size: 14px;
        }}
        .legend-label {{ cursor: pointer; user-select: none; }}
        .dot {{ width: 12px; height: 12px; border-radius: 50%; display: inline-block; }}
        
        .backend {{ background-color: #97C2FC; border: 1px solid #2B7CE9; }}
        .core {{ background-color: #7BE141; border: 1px solid #41A906; }}
        .frontend {{ background-color: #FFC0CB; border: 1px solid #FB7E81; }}
        
        #search-container {{ margin-top: 15px; margin-bottom: 15px; }}
        input {{ 
            width: 100%; padding: 8px; 
            border: 1px solid var(--border-color); 
            border-radius: 4px; 
            box-sizing: border-box; 
            background: var(--bg-color);
            color: var(--text-color);
        }}
        
        .btn-group {{ display: flex; gap: 10px; }}
        .btn {{
            flex: 1;
            padding: 8px 12px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 13px;
            font-weight: 500;
            background: var(--btn-bg);
            color: var(--btn-text);
            transition: background 0.2s;
        }}
        .btn:hover {{ background: var(--btn-hover); }}
        
        .stats-row {{ display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 5px; opacity: 0.8; }}
        
        #theme-toggle {{
            position: absolute;
            top: 20px;
            right: 20px;
            background: var(--panel-bg);
            border: 1px solid var(--border-color);
            border-radius: 50%;
            width: 40px;
            height: 40px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            color: var(--text-color);
            z-index: 20;
            box-shadow: var(--panel-shadow);
            transition: background 0.3s;
        }}
        #theme-toggle:hover {{ background: var(--bg-color); }}
        
        /* Checkbox styling */
        input[type="checkbox"] {{ cursor: pointer; }}
    </style>
</head>
<body>

<button id="theme-toggle" onclick="toggleTheme()" title="Toggle Dark Mode">
    <span class="material-icons">dark_mode</span>
</button>

<div id="controls" class="panel">
    <h2>Architecture Map</h2>
    
    <div class="stats-row"><span>Modules:</span> <b>{stats['modules']}</b></div>
    <div class="stats-row"><span>Files:</span> <b>{stats['files']}</b></div>
    <div class="stats-row"><span>Dependencies:</span> <b>{stats['edges']}</b></div>
    <hr style="border: 0; border-top: 1px solid var(--border-color); margin: 10px 0;">
    
    <div id="search-container">
        <input type="text" id="search" placeholder="Search modules..." onkeyup="searchNode()">
    </div>
    
    <div class="legend-grid">
        <input type="checkbox" checked onchange="toggleGroup('backend')" id="cb-backend">
        <div class="dot backend"></div>
        <label for="cb-backend" class="legend-label">Backend</label>
        
        <input type="checkbox" checked onchange="toggleGroup('core')" id="cb-core">
        <div class="dot core"></div>
        <label for="cb-core" class="legend-label">Core Logic</label>
        
        <input type="checkbox" checked onchange="toggleGroup('frontend')" id="cb-frontend">
        <div class="dot frontend"></div>
        <label for="cb-frontend" class="legend-label">Frontend</label>
    </div>
    
    <div class="btn-group">
        <button class="btn" onclick="resetView()">Clear & Reset</button>
        <button class="btn" onclick="fitAll()">Fit All</button>
    </div>
</div>

<div id="info-panel" class="panel">
    <h3 id="panel-title">Module</h3>
    <div id="panel-content"></div>
</div>

<div id="mynetwork"></div>

<script type="text/javascript">
    const data = {json.dumps(graph_data)};
    let network;
    let allNodes = new vis.DataSet(data.nodes);
    let allEdges = new vis.DataSet(data.edges);
    
    // Theme Colors
    const themes = {{
        light: {{ bg: '#f0f2f5', font: '#333', edge: '#888' }},
        dark: {{ bg: '#1e1e1e', font: '#dcddde', edge: '#666' }}
    }};
    let currentTheme = 'light';

    const options = {{
        nodes: {{
            shape: 'dot',
            scaling: {{ min: 10, max: 30, label: {{ min: 8, max: 20, drawThreshold: 5, maxVisible: 20 }} }},
            font: {{ size: 14, face: 'Inter, Tahoma', color: '#333', strokeWidth: 2, strokeColor: '#fff' }},
            borderWidth: 2
        }},
        edges: {{
            width: 0.5,
            color: {{ inherit: 'from', opacity: 0.5 }},
            smooth: {{ type: 'continuous', roundness: 0.5 }},
            arrows: {{ to: {{ enabled: true, scaleFactor: 0.5 }} }}
        }},
        physics: {{
            stabilization: false,
            barnesHut: {{ 
                gravitationalConstant: -12000, // Increased repulsion
                centralGravity: 0.3,
                springLength: 120, // Increased spacing
                springConstant: 0.04,
                damping: 0.09,
                avoidOverlap: 0.2
            }},
            adaptiveTimestep: true
        }},
        interaction: {{ tooltipDelay: 200, hideEdgesOnDrag: true, hover: true, zoomView: true }}
    }};

    function init() {{
        const container = document.getElementById('mynetwork');
        network = new vis.Network(container, {{ nodes: allNodes, edges: allEdges }}, options);
        
        network.on("click", function (params) {{
            if (params.nodes.length > 0) {{
                const nodeId = params.nodes[0];
                showNodeDetails(nodeId);
                highlightNeighborhood(nodeId);
            }} else {{
                hideNodeDetails();
                resetHighlight();
            }}
        }});
    }}

    function showNodeDetails(nodeId) {{
        const node = allNodes.get(nodeId);
        if (node) {{
            document.getElementById('info-panel').style.display = 'block';
            document.getElementById('panel-title').innerText = node.label;
            document.getElementById('panel-content').innerHTML = node.title;
        }}
    }}

    function hideNodeDetails() {{
        document.getElementById('info-panel').style.display = 'none';
    }}

    function highlightNeighborhood(nodeId) {{
        const connectedNodes = network.getConnectedNodes(nodeId);
        const allNodeIds = allNodes.getIds();
        
        const dimColor = currentTheme === 'dark' ? '#333' : '#e0e0e0';
        const dimFont = currentTheme === 'dark' ? '#555' : '#ccc';
        
        const updateArray = [];
        allNodeIds.forEach(id => {{
            if (id !== nodeId && !connectedNodes.includes(id)) {{
                updateArray.push({{ 
                    id: id, 
                    color: {{ background: dimColor, border: dimColor }}, 
                    font: {{ color: dimFont }} 
                }});
            }} else {{
                // Reset to default (group color)
                updateArray.push({{ 
                    id: id, 
                    color: null, 
                    font: {{ color: currentTheme === 'dark' ? '#dcddde' : '#333' }} 
                }});
            }}
        }});
        allNodes.update(updateArray);
    }}

    function resetHighlight() {{
        const allNodeIds = allNodes.getIds();
        const updateArray = allNodeIds.map(id => ({{ 
            id: id, 
            color: null, 
            font: {{ color: currentTheme === 'dark' ? '#dcddde' : '#333' }} 
        }}));
        allNodes.update(updateArray);
    }}

    function toggleGroup(group) {{
        const checkbox = document.getElementById('cb-' + group);
        const nodesToToggle = allNodes.get({{ filter: item => item.group === group }});
        
        nodesToToggle.forEach(node => {{
            allNodes.update({{ id: node.id, hidden: !checkbox.checked }});
        }});
    }}

    function searchNode() {{
        const term = document.getElementById('search').value.toLowerCase();
        if (!term) return;
        
        const foundNodes = allNodes.get({{ filter: item => item.label.toLowerCase().includes(term) }});
        
        if (foundNodes.length > 0) {{
            const nodeId = foundNodes[0].id;
            network.focus(nodeId, {{ scale: 1.2, animation: true }});
            network.selectNodes([nodeId]);
            showNodeDetails(nodeId);
            highlightNeighborhood(nodeId);
        }}
    }}

    function resetView() {{
        network.fit();
        resetHighlight();
        hideNodeDetails();
        document.getElementById('search').value = '';
        // Reset checkboxes
        ['backend', 'core', 'frontend'].forEach(g => {{
            document.getElementById('cb-' + g).checked = true;
            toggleGroup(g);
        }});
    }}
    
    function fitAll() {{
        network.fit({{ animation: true }});
    }}

    function toggleTheme() {{
        currentTheme = currentTheme === 'light' ? 'dark' : 'light';
        document.body.classList.toggle('dark-mode');
        
        const icon = document.querySelector('#theme-toggle span');
        icon.textContent = currentTheme === 'light' ? 'dark_mode' : 'light_mode';
        
        // Update node font colors and strokes
        const textColor = currentTheme === 'light' ? '#333' : '#dcddde';
        const strokeColor = currentTheme === 'light' ? '#fff' : '#2b2b2b';
        
        options.nodes.font.color = textColor;
        options.nodes.font.strokeColor = strokeColor;
        network.setOptions(options);
        
        // Refresh nodes
        resetHighlight();
    }}

    init();
</script>

</body>
</html>
    """
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html_content)
    
    print(f"Interactive diagram generated at {OUTPUT_FILE}")
    print(f"Stats: {stats}")

if __name__ == "__main__":
    generate_interactive_diagram()
