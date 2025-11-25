import json
import os

ROOT_DIR = r"c:/Users/SASINDU/Desktop/IRWA Group Repo/dynamic-pricing-ai-IRWA_PROJECT"
JSON_FILE = os.path.join(ROOT_DIR, "codebase_graph_data.json")
OUTPUT_FILE = os.path.join(ROOT_DIR, "codebase_graph_full.html")

def generate_html():
    print(f"Reading data from {JSON_FILE}...")
    try:
        with open(JSON_FILE, "r", encoding="utf-8") as f:
            graph_data = json.load(f)
    except Exception as e:
        print(f"Error reading JSON file: {e}")
        return

    # Serialize data to JSON string
    json_str = json.dumps(graph_data)
    
    # Escape </script> to prevent breaking the HTML
    json_str = json_str.replace("</script>", "<\\/script>")

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Full Codebase Dependency Graph</title>
    <script src="https://d3js.org/d3.v7.min.js"></script>
    <style>
        body {{
            background-color: #0d1117;
            color: #c9d1d9;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
            margin: 0;
            overflow: hidden;
        }}
        #container {{
            width: 100vw;
            height: 100vh;
            position: absolute;
            top: 0;
            left: 0;
            z-index: 1;
        }}
        /* UI Overlay - High Z-Index to ensure clickability */
        .ui-layer {{
            position: absolute;
            z-index: 100;
            pointer-events: none; /* Let clicks pass through empty areas */
            width: 100%;
            height: 100%;
        }}
        .interactive-panel {{
            pointer-events: auto; /* Re-enable clicks for panels */
            background: rgba(22, 27, 34, 0.85);
            border: 1px solid #30363d;
            backdrop-filter: blur(8px);
            border-radius: 8px;
            padding: 16px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        }}
        
        #controls {{
            top: 20px;
            left: 20px;
            width: 280px;
            position: absolute;
        }}
        
        #search-panel {{
            top: 20px;
            right: 20px;
            width: 250px;
            position: absolute;
        }}

        #legend {{
            bottom: 20px;
            right: 20px;
            position: absolute;
        }}

        #info-panel {{
            bottom: 20px;
            left: 20px;
            width: 300px;
            max-height: 200px;
            overflow-y: auto;
            position: absolute;
            display: none; /* Hidden by default */
        }}

        .control-group {{
            margin-bottom: 12px;
        }}
        .control-group:last-child {{
            margin-bottom: 0;
        }}
        label {{
            display: block;
            margin-bottom: 6px;
            font-size: 12px;
            font-weight: 600;
            color: #8b949e;
        }}
        select, input[type="text"] {{
            width: 100%;
            background: #0d1117;
            color: #c9d1d9;
            border: 1px solid #30363d;
            padding: 6px;
            border-radius: 4px;
            font-size: 12px;
            box-sizing: border-box;
        }}
        select:focus, input:focus {{
            border-color: #58a6ff;
            outline: none;
        }}
        input[type="range"] {{
            width: 100%;
            margin: 0;
        }}
        button {{
            background: #238636;
            color: white;
            border: none;
            padding: 6px 12px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 12px;
            font-weight: 600;
            width: 100%;
            transition: background 0.2s;
        }}
        button:hover {{
            background: #2ea043;
        }}
        button.secondary {{
            background: #30363d;
        }}
        button.secondary:hover {{
            background: #3b434b;
        }}

        .legend-item {{
            display: flex;
            align-items: center;
            margin-bottom: 6px;
            font-size: 12px;
            cursor: pointer;
            opacity: 0.8;
            transition: opacity 0.2s;
        }}
        .legend-item:hover {{
            opacity: 1;
        }}
        .legend-item.dimmed {{
            opacity: 0.3;
        }}
        .legend-color {{
            width: 12px;
            height: 12px;
            border-radius: 50%;
            margin-right: 8px;
        }}

        /* Graph Elements */
        .node circle {{
            stroke: #fff;
            stroke-width: 1px;
            cursor: pointer;
            transition: all 0.2s ease;
        }}
        .node.dimmed circle {{
            opacity: 0.1;
        }}
        .node.highlighted circle {{
            stroke: #58a6ff;
            stroke-width: 3px;
            filter: drop-shadow(0 0 8px rgba(88, 166, 255, 0.6));
            opacity: 1;
        }}
        .link {{
            fill: none;
            stroke: #30363d;
            stroke-opacity: 0.4;
            transition: all 0.2s;
        }}
        .link.dimmed {{
            opacity: 0.05 !important;
        }}
        .link.highlighted {{
            stroke: #58a6ff;
            stroke-opacity: 0.8 !important;
        }}
        
        .node text {{
            font-size: 10px;
            fill: #8b949e;
            pointer-events: none;
            opacity: 0; 
            transition: opacity 0.2s;
            text-shadow: 2px 2px 2px #0d1117;
        }}
        .node:hover text, .node.highlighted text {{
            opacity: 1;
            fill: #c9d1d9;
            font-weight: bold;
            z-index: 10;
        }}

        #tooltip {{
            position: absolute;
            padding: 12px;
            background: rgba(22, 27, 34, 0.95);
            border: 1px solid #30363d;
            border-radius: 6px;
            pointer-events: none;
            opacity: 0;
            transition: opacity 0.1s;
            max-width: 350px;
            z-index: 1000;
            box-shadow: 0 8px 24px rgba(0,0,0,0.5);
            font-size: 12px;
            line-height: 1.4;
        }}
        .search-result {{
            padding: 4px 8px;
            cursor: pointer;
            border-bottom: 1px solid #30363d;
        }}
        .search-result:hover {{
            background: #161b22;
        }}
        #search-results {{
            max-height: 200px;
            overflow-y: auto;
            background: #0d1117;
            border: 1px solid #30363d;
            border-top: none;
            display: none;
            position: absolute;
            width: 100%;
            z-index: 101;
            box-sizing: border-box;
        }}
        #loading {{
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            font-size: 24px;
            color: #58a6ff;
            z-index: 200;
            pointer-events: none;
        }}
    </style>
</head>
<body>
    <div id="container"></div>
    <div id="loading">Loading Graph...</div>
    
    <!-- UI Layer -->
    <div class="ui-layer">
        <div id="controls" class="interactive-panel">
            <div class="control-group">
                <label>Node Size By</label>
                <select id="sizeMetric">
                    <option value="size">File Size</option>
                    <option value="degree" selected>Connectivity (Degree)</option>
                </select>
            </div>
            <div class="control-group">
                <label>Link Opacity</label>
                <input type="range" min="0.1" max="1" step="0.1" value="0.4" id="opacitySlider">
            </div>
            <div class="control-group">
                <label>Force Strength</label>
                <input type="range" min="-1000" max="-50" step="50" value="-300" id="forceSlider">
            </div>
            <div class="control-group" style="display: flex; gap: 8px;">
                <button id="togglePhysics" class="secondary">Pause Physics</button>
                <button id="resetView" class="secondary">Reset View</button>
            </div>
        </div>

        <div id="search-panel" class="interactive-panel">
            <label>Search File</label>
            <div style="position: relative;">
                <input type="text" id="searchInput" placeholder="Type filename...">
                <div id="search-results"></div>
            </div>
        </div>

        <div id="legend" class="interactive-panel">
            <div style="font-weight: 600; margin-bottom: 8px; font-size: 12px; color: #8b949e;">Groups (Click to Filter)</div>
            <div class="legend-item" data-group="frontend"><div class="legend-color" style="background: #ff7b72;"></div>Frontend</div>
            <div class="legend-item" data-group="backend"><div class="legend-color" style="background: #79c0ff;"></div>Backend</div>
            <div class="legend-item" data-group="core"><div class="legend-color" style="background: #d2a8ff;"></div>Core</div>
            <div class="legend-item" data-group="other"><div class="legend-color" style="background: #8b949e;"></div>Other</div>
        </div>
        
        <div id="info-panel" class="interactive-panel">
            <h3 id="info-title" style="margin: 0 0 8px 0; color: #58a6ff; font-size: 14px;"></h3>
            <div id="info-content" style="font-size: 12px; color: #c9d1d9;"></div>
        </div>
    </div>

    <div id="tooltip"></div>
    <div id="error-log" style="display: none; position: absolute; top: 10px; right: 10px; width: 400px; background: rgba(255,0,0,0.9); color: white; padding: 10px; border-radius: 5px; z-index: 9999; font-family: monospace; white-space: pre-wrap;"></div>

    <!-- Data Injection -->
    <script id="graph-data" type="application/json">
    {json_str}
    </script>

    <script>
        // Error Logging Mechanism
        function logError(msg) {{
            const errDiv = document.getElementById("error-log");
            errDiv.style.display = "block";
            errDiv.textContent += "ERROR: " + msg + "\\n";
            console.error(msg);
        }}

        window.onerror = function(msg, url, lineNo, columnNo, error) {{
            logError(`${{msg}} at ${{lineNo}}:${{columnNo}}`);
            return false;
        }};

        console.log("Initializing visualization...");
        let data;
        try {{
            const rawData = document.getElementById("graph-data").textContent;
            data = JSON.parse(rawData);
            console.log("Data loaded successfully:", data.nodes.length, "nodes,", data.links.length, "links");
        }} catch (e) {{
            logError("Failed to parse graph data: " + e.message);
            document.getElementById("loading").textContent = "Error loading data. See console.";
            throw e;
        }}

        const width = window.innerWidth;
        const height = window.innerHeight;
        console.log("Viewport size:", width, "x", height);

        // Pre-process data & Randomize Initial Positions
        const degreeMap = {{}};
        const neighbors = {{}}; 
        
        data.nodes.forEach(n => {{
            neighbors[n.id] = new Set();
            // Randomize initial positions to prevent stacking
            n.x = Math.random() * width;
            n.y = Math.random() * height;
        }});
        
        data.links.forEach(l => {{
            degreeMap[l.source] = (degreeMap[l.source] || 0) + 1;
            degreeMap[l.target] = (degreeMap[l.target] || 0) + 1;
            if (neighbors[l.source]) neighbors[l.source].add(l.target);
            if (neighbors[l.target]) neighbors[l.target].add(l.source);
        }});
        
        data.nodes.forEach(n => {{
            n.degree = degreeMap[n.id] || 0;
        }});

        const color = d3.scaleOrdinal()
            .domain(["frontend", "backend", "core", "other"])
            .range(["#ff7b72", "#79c0ff", "#d2a8ff", "#8b949e"]);

        const sizeScaleFile = d3.scaleLog()
            .domain([1, d3.max(data.nodes, d => d.size || 1)])
            .range([4, 20]);
            
        const sizeScaleDegree = d3.scaleLinear()
            .domain([0, d3.max(data.nodes, d => d.degree || 0)])
            .range([4, 25]);

        let currentSizeMetric = "degree";
        let activeNode = null; 
        let activeGroup = null;

        function getNodeSize(d) {{
            return currentSizeMetric === "size" ? sizeScaleFile(d.size || 1) : sizeScaleDegree(d.degree || 0);
        }}

        // Zoom behavior
        const zoom = d3.zoom()
            .scaleExtent([0.1, 4])
            .on("zoom", (event) => g.attr("transform", event.transform));

        const svg = d3.select("#container").append("svg")
            .attr("width", "100%")
            .attr("height", "100%")
            .call(zoom)
            .on("dblclick.zoom", null);

        const g = svg.append("g");

        // Markers
        svg.append("defs").selectAll("marker")
            .data(["end"])
            .enter().append("marker")
            .attr("id", "arrow")
            .attr("viewBox", "0 -5 10 10")
            .attr("refX", 25)
            .attr("refY", 0)
            .attr("markerWidth", 6)
            .attr("markerHeight", 6)
            .attr("orient", "auto")
            .append("path")
            .attr("d", "M0,-5L10,0L0,5")
            .attr("fill", "#30363d");

        console.log("Starting simulation...");
        // Increased repulsion force
        const simulation = d3.forceSimulation(data.nodes)
            .force("link", d3.forceLink(data.links).id(d => d.id).distance(100))
            .force("charge", d3.forceManyBody().strength(-500)) 
            .force("center", d3.forceCenter(width / 2, height / 2))
            .force("collide", d3.forceCollide().radius(d => getNodeSize(d) + 10));

        const link = g.append("g")
            .selectAll("path")
            .data(data.links)
            .enter().append("path")
            .attr("class", "link")
            .attr("marker-end", "url(#arrow)")
            .attr("stroke-width", d => Math.min(3, Math.max(1, (d.symbols ? d.symbols.length : 1) * 0.5)));

        const node = g.append("g")
            .selectAll("g")
            .data(data.nodes)
            .enter().append("g")
            .attr("class", "node")
            .call(d3.drag()
                .on("start", dragstarted)
                .on("drag", dragged)
                .on("end", dragended))
            .on("click", handleNodeClick);

        const circles = node.append("circle")
            .attr("r", d => getNodeSize(d))
            .attr("fill", d => color(d.group));

        node.append("text")
            .attr("dx", 12)
            .attr("dy", 4)
            .text(d => d.name);

        // Hide loading
        d3.select("#loading").style("display", "none");

        // Simulation Tick with Safety Check
        simulation.on("tick", () => {{
            // Check for NaN
            if (data.nodes[0] && (isNaN(data.nodes[0].x) || isNaN(data.nodes[0].y))) {{
                logError("Simulation produced NaN coordinates. Stopping.");
                simulation.stop();
                return;
            }}

            link.attr("d", d => {{
                return `M${{d.source.x}},${{d.source.y}}L${{d.target.x}},${{d.target.y}}`;
            }});

            node.attr("transform", d => `translate(${{d.x}},${{d.y}})`);
        }});

        // --- Interactions ---

        function handleNodeClick(event, d) {{
            event.stopPropagation(); 
            
            if (activeNode === d) {{
                resetHighlight();
            }} else {{
                highlightNode(d);
            }}
        }}

        function highlightNode(d) {{
            activeNode = d;
            
            node.classed("dimmed", true).classed("highlighted", false);
            link.classed("dimmed", true).classed("highlighted", false);

            const neighborIds = neighbors[d.id];
            
            node.filter(n => n.id === d.id || (neighborIds && neighborIds.has(n.id)))
                .classed("dimmed", false)
                .classed("highlighted", true);

            link.filter(l => l.source.id === d.id || l.target.id === d.id)
                .classed("dimmed", false)
                .classed("highlighted", true);
                
            const infoPanel = d3.select("#info-panel");
            infoPanel.style("display", "block");
            d3.select("#info-title").text(d.name);
            d3.select("#info-content").html(`
                <strong>Path:</strong> ${{d.id}}<br>
                <strong>Type:</strong> ${{d.group}}<br>
                <strong>Size:</strong> ${{d.size}} bytes<br>
                <strong>Connections:</strong> ${{d.degree}}<br>
                <hr style="border-color: #30363d;">
                <strong>Imports (${{data.links.filter(l => l.source.id === d.id).length}}):</strong><br>
                ${{data.links.filter(l => l.source.id === d.id).map(l => `&rarr; ${{l.target.name}}`).slice(0, 10).join("<br>")}}${{data.links.filter(l => l.source.id === d.id).length > 10 ? "<br>..." : ""}}
            `);
        }}

        function resetHighlight() {{
            activeNode = null;
            node.classed("dimmed", false).classed("highlighted", false);
            link.classed("dimmed", false).classed("highlighted", false);
            d3.select("#info-panel").style("display", "none");
        }}
        
        svg.on("click", () => {{
            resetHighlight();
            activeGroup = null;
            d3.selectAll(".legend-item").classed("dimmed", false);
            node.style("display", "block");
            link.style("display", "block");
        }});

        node.on("mouseover", (event, d) => {{
            if (activeNode) return;
            
            const tooltip = d3.select("#tooltip");
            tooltip.transition().duration(100).style("opacity", 1);
            tooltip.html(`<strong>${{d.name}}</strong><br>${{d.group}}`)
                .style("left", (event.pageX + 15) + "px")
                .style("top", (event.pageY - 15) + "px");
        }})
        .on("mouseout", () => {{
            if (activeNode) return;
            d3.select("#tooltip").transition().duration(200).style("opacity", 0);
        }});

        // --- Controls Logic ---

        d3.select("#sizeMetric").on("change", function() {{
            currentSizeMetric = this.value;
            circles.transition().duration(500).attr("r", d => getNodeSize(d));
            simulation.force("collide").radius(d => getNodeSize(d) + 10);
            simulation.alpha(0.3).restart();
        }});

        d3.select("#opacitySlider").on("input", function() {{
            d3.selectAll(".link").style("stroke-opacity", this.value);
        }});

        d3.select("#forceSlider").on("input", function() {{
            simulation.force("charge").strength(+this.value);
            simulation.alpha(1).restart();
        }});

        let isPhysicsActive = true;
        d3.select("#togglePhysics").on("click", function() {{
            if (isPhysicsActive) {{
                simulation.stop();
                this.textContent = "Resume Physics";
            }} else {{
                simulation.alpha(1).restart();
                this.textContent = "Pause Physics";
            }}
            isPhysicsActive = !isPhysicsActive;
        }});

        d3.select("#resetView").on("click", () => {{
            svg.transition().duration(750).call(zoom.transform, d3.zoomIdentity);
        }});

        // Search
        const searchInput = document.getElementById("searchInput");
        const searchResults = document.getElementById("search-results");
        
        searchInput.addEventListener("input", (e) => {{
            const val = e.target.value.toLowerCase();
            searchResults.innerHTML = "";
            if (val.length < 2) {{
                searchResults.style.display = "none";
                return;
            }}
            
            const matches = data.nodes.filter(n => n.name.toLowerCase().includes(val)).slice(0, 10);
            if (matches.length > 0) {{
                searchResults.style.display = "block";
                matches.forEach(n => {{
                    const div = document.createElement("div");
                    div.className = "search-result";
                    div.textContent = n.name;
                    div.onclick = () => {{
                        highlightNode(n);
                        searchResults.style.display = "none";
                        searchInput.value = n.name;
                        
                        // Center view on node
                        svg.transition().duration(750).call(
                            zoom.transform, 
                            d3.zoomIdentity.translate(width/2, height/2).scale(1.5).translate(-n.x, -n.y)
                        );
                    }};
                    searchResults.appendChild(div);
                }});
            }} else {{
                searchResults.style.display = "none";
            }}
        }});

        // Legend Filter
        d3.selectAll(".legend-item").on("click", function() {{
            const group = this.getAttribute("data-group");
            
            if (activeGroup === group) {{
                // Reset
                activeGroup = null;
                d3.selectAll(".legend-item").classed("dimmed", false);
                node.style("display", "block");
                link.style("display", "block");
            }} else {{
                // Filter
                activeGroup = group;
                d3.selectAll(".legend-item").classed("dimmed", true);
                d3.select(this).classed("dimmed", false);
                
                node.style("display", n => n.group === group ? "block" : "none");
                link.style("display", l => {{
                    const sourceGroup = l.source.group || l.source.data.group; // Handle d3 object vs raw
                    const targetGroup = l.target.group || l.target.data.group;
                    return (sourceGroup === group && targetGroup === group) ? "block" : "none";
                }});
            }}
        }});

        // Simulation Drag
        function dragstarted(event, d) {{
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
        }}

        function dragged(event, d) {{
            d.fx = event.x;
            d.fy = event.y;
        }}

        function dragended(event, d) {{
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
        }}
    </script>
</body>
</html>
"""
    
    print(f"Writing to {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html_content)
    print("Done.")

if __name__ == "__main__":
    generate_html()
