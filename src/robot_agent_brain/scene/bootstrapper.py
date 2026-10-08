"""Component bootstrap with configured library resources and measured bounds."""
import random

from ..contracts.bootstrap import BootstrapResult
from ..contracts.scene import SceneConfig, SceneObject, SceneComponent, RobotDriverProperties
from ..contracts.spatial import ResolvedSelectionRelation
from ..grounding.scene_relation_resolver import SceneRelationResolver
from .asset_resolver import AssetResolver
from .geometry import world_bounds
from .scene_graph import WorldTransform

IDENTITY = ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.))


def make_object(identifier, name, reference, position, *, category=None, support=None, driver=None):
    components = [
        SceneComponent(component_type="Transform", properties={
            "position": list(position), "quaternion_xyzw": [0, 0, 0, 1],
            "scale": [1, 1, 1], "parent": None}),
        SceneComponent(component_type="MetadataRef", properties={"path": reference}),
    ]
    if category is not None:
        components.append(SceneComponent(component_type="Semantic", properties={
            "semantic_name": name, "category": category, "support": support}))
    if driver is not None:
        components.append(SceneComponent(component_type="RobotDriver", properties=driver.model_dump(mode="json")))
    return SceneObject(object_id_in_scene=identifier, object_name_in_scene=name, components=components)


class SceneBootstrapper:
    def __init__(self, assets, defaults, *, robot="ur5e", seed=0, table_metadata_ref=None,
                 robot_metadata_ref=None, robot_driver=None, aliases=None, category_aliases=None):
        self.assets, self.defaults, self.robot, self.seed = assets, defaults, robot, seed
        self.table_ref, self.robot_ref = table_metadata_ref, robot_metadata_ref
        self.driver = robot_driver
        self.resolver = AssetResolver(assets, aliases=aliases, category_aliases=category_aliases)

    def prepare(self, turn, *, scene_id):
        if turn.status != "accepted" or turn.turn_kind not in {"robot_task", "scene_edit"}:
            raise ValueError("scene_required")
        if self.table_ref is None or self.robot_ref is None or self.driver is None:
            raise ValueError("bootstrap_config_missing: configure table/robot MetadataRef and RobotDriver")
        driver = RobotDriverProperties.model_validate(self.driver.model_dump() if hasattr(self.driver, "model_dump") else self.driver)
        if turn.turn_kind == "robot_task":
            entities, relations = turn.task_intent.entities, turn.task_intent.spatial_relations
        else:
            plan = turn.scene_edit
            if all(op.operation == "remove" for op in plan.operations):
                raise ValueError("scene_required: cannot create objects only to remove them")
            defined, needed = set(), set()
            for op in plan.operations:
                if op.reference and op.reference not in defined:
                    needed.add(op.reference)
                if op.operation == "add":
                    if op.target in needed:
                        raise ValueError("bootstrap_entity_lifecycle_conflict")
                    defined.add(op.target)
                elif op.target not in defined:
                    needed.add(op.target)
            while True:
                refs = {r.reference for r in plan.relations if r.subject in needed and r.reference}
                if refs <= needed:
                    break
                needed.update(refs)
            entities = [e for e in plan.entities if e.entity_id in needed]
            relations = [r for r in plan.relations if r.subject in needed]
        initial = [r for r in relations if r.scope != "goal"]
        supported = {"left", "right", "front", "back", "leftmost", "rightmost", "frontmost", "backmost",
                     "nearest", "farthest", "left_of", "right_of", "front_of", "behind"}
        if any(r.relation.value not in supported for r in initial):
            raise ValueError("bootstrap_relation_unsupported: initial relation requires geometry not supplied")
        table_model = self.assets.resolve(self.table_ref)
        self.assets.resolve(self.robot_ref)  # Require a real configured resource.
        table_id, robot_id = self.defaults.table_object_id, self.defaults.robot_object_id
        table = make_object(table_id, "table", self.table_ref, self.defaults.table_position, category="surface")
        robot = make_object(robot_id, self.robot, self.robot_ref, self.defaults.robot_position, driver=driver)
        table_low, table_high = world_bounds(table_model, WorldTransform(self.defaults.table_position, IDENTITY))
        if any(self.defaults.workspace_min[i] < table_low[i] or self.defaults.workspace_max[i] > table_high[i] for i in (0, 1)):
            raise ValueError("bootstrap_workspace_outside_support")
        specs, candidates, bindings = [], {}, {}
        assumptions = ["source=system_default: tabletop placement; x right, y front, z up"]
        next_id = max(table_id, robot_id) + 1
        for entity in entities:
            binding = self.resolver.resolve(entity)
            model = binding.model
            bindings[entity.entity_id] = model.metadata_ref
            assumptions.extend(binding.assumptions)
            count = entity.count
            if entity.all_available:
                count = self.defaults.initial_counts.get(model.semantic_name)
                if count is None:
                    raise ValueError("bootstrap_quantity_unspecified: " + model.semantic_name)
                assumptions.append(f"source=system_default: {model.semantic_name} count={count}")
            if model.metadata_ref == self.table_ref:
                if count != 1:
                    raise ValueError("bootstrap_layout_failed: multiple base tables unsupported")
                candidates[entity.entity_id] = [table_id]
                continue
            candidates[entity.entity_id] = []
            for _ in range(count):
                if next_id > 2**53 - 1:
                    raise ValueError("scene_object_ids_exhausted")
                specs.append((next_id, model, model.category or entity.category))
                candidates[entity.entity_id].append(next_id)
                next_id += 1
        rng = random.Random(self.seed)
        xmin, ymin = self.defaults.workspace_min
        xmax, ymax = self.defaults.workspace_max
        for _ in range(self.defaults.max_attempts):
            placed, bounds = [], []
            for identifier, model, category in specs:
                low, high = model.local_aabb_min_m, model.local_aabb_max_m
                limits = ((xmin - low[0], xmax - high[0]), (ymin - low[1], ymax - high[1]))
                if any(a > b for a, b in limits):
                    raise ValueError("bootstrap_layout_failed: object exceeds workspace")
                position = (rng.uniform(*limits[0]), rng.uniform(*limits[1]), table_high[2] - low[2])
                box = world_bounds(model, WorldTransform(position, IDENTITY))
                gap = self.defaults.clearance_m
                if any(all(box[0][i] < other[1][i] + gap and other[0][i] < box[1][i] + gap
                           for i in (0, 1)) for other in bounds):
                    break
                placed.append(make_object(identifier, model.semantic_name, model.metadata_ref,
                                          position, category=category, support=table_id))
                bounds.append(box)
            if len(placed) != len(specs):
                continue
            scene = SceneConfig(scene_schema_version=1, scene_version=1, scene_id=scene_id,
                                scene_name="Generated task scene", objects=[table, robot, *placed])
            by_id = {o.object_id_in_scene: o for o in scene.objects}
            valid = True
            for entity in entities:
                selection = []
                for rel in initial:
                    if rel.subject != entity.entity_id:
                        continue
                    ref = None
                    if rel.reference is not None:
                        if len(candidates.get(rel.reference, [])) != 1:
                            raise ValueError("bootstrap_relation_unsupported: reference is not unique")
                        ref = candidates[rel.reference][0]
                    selection.append(ResolvedSelectionRelation(relation=rel.relation, reference_object_id=ref))
                matches = SceneRelationResolver().resolve([by_id[i] for i in candidates[entity.entity_id]], selection, scene)
                required = 1 if entity.quantity_mode == "candidate_pool" else len(candidates[entity.entity_id])
                if len(matches) != required:
                    valid = False
                    break
            if valid:
                return BootstrapResult(scene=scene, entity_candidates=candidates, asset_bindings=bindings,
                                       assumptions=list(dict.fromkeys(assumptions)))
        raise ValueError("bootstrap_layout_failed: exhausted configured attempts")
