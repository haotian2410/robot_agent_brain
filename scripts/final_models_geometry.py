"""Offline OBJ bounds and fixed assembly transforms; no articulated FK."""
import math
import xml.etree.ElementTree as ET
from pathlib import Path


def contained(root, base, relative):
    target = (base / relative).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError(f"asset_path_outside_library: {target}")
    if not target.is_file():
        raise FileNotFoundError(f"asset_file_missing: {target}")
    return target


def vertices(root, path):
    points = []
    for line in path.read_text(encoding="utf-8", errors="strict").splitlines():
        fields = line.split()
        if fields and fields[0] == "v":
            values = [float(v) for v in fields[1:]]
            if len(values) < 3 or not all(math.isfinite(v) for v in values):
                raise ValueError("asset_vertex_invalid")
            divisor = values[3] if len(values) == 4 else 1
            points.append(tuple(v / divisor for v in values[:3]))
        if fields and fields[0] == "mtllib":
            for material in fields[1:]:
                mtl = contained(root, path.parent, material)
                for row in mtl.read_text().splitlines():
                    terms = row.split()
                    if terms and (terms[0].startswith("map_") or terms[0] in {"bump", "disp"}):
                        contained(root, mtl.parent, terms[-1])
    if not points:
        raise ValueError(f"asset_vertices_missing: {path}")
    return points


def origin(element, point):
    if element is None:
        return point
    xyz = [float(v) for v in element.get("xyz", "0 0 0").split()]
    roll, pitch, yaw = [float(v) for v in element.get("rpy", "0 0 0").split()]
    x, y, z = point
    y, z = math.cos(roll)*y-math.sin(roll)*z, math.sin(roll)*y+math.cos(roll)*z
    x, z = math.cos(pitch)*x+math.sin(pitch)*z, -math.sin(pitch)*x+math.cos(pitch)*z
    x, y = math.cos(yaw)*x-math.sin(yaw)*y, math.sin(yaw)*x+math.cos(yaw)*y
    return tuple(a+b for a,b in zip((x,y,z), xyz))


def measured(root, path):
    if path.suffix == ".obj":
        points = vertices(root, path)
    elif path.suffix == ".urdf":
        tree = ET.parse(path).getroot()
        for mesh in tree.findall(".//mesh"):
            mesh_path = contained(root, path.parent, mesh.attrib["filename"])
            vertices(root, mesh_path)
        for texture in tree.findall(".//texture"):
            if texture.get("filename"):
                contained(root, path.parent, texture.get("filename"))
        # Moving link poses belong to the platform, not a guessed zero joint pose.
        if any(j.get("type") != "fixed" for j in tree.findall("joint")):
            return None
        parents = {j.find("child").get("link"): j for j in tree.findall("joint")}
        points = []
        for link in tree.findall("link"):
            for visual in link.findall("visual"):
                mesh = visual.find("geometry/mesh")
                if mesh is None:
                    raise ValueError("static_assembly_visual_not_mesh")
                scale = [float(v) for v in mesh.get("scale", "1 1 1").split()]
                local = [origin(visual.find("origin"), tuple(a*b for a,b in zip(p,scale)))
                         for p in vertices(root, contained(root,path.parent,mesh.get("filename")))]
                current, seen = link.get("name"), set()
                while current in parents:
                    if current in seen:
                        raise ValueError("static_assembly_cycle")
                    seen.add(current)
                    joint = parents[current]
                    local = [origin(joint.find("origin"), p) for p in local]
                    current = joint.find("parent").get("link")
                points.extend(local)
    else:
        raise ValueError("asset_geometry_format_unsupported")
    low = [min(p[i] for p in points) for i in range(3)]
    high = [max(p[i] for p in points) for i in range(3)]
    return {"dimensions_m": [b-a for a,b in zip(low,high)],
            "local_aabb_min_m": low, "local_aabb_max_m": high}
