"""Pure initial-scene construction: no provider, platform, files or task execution."""
import random
from ..contracts.bootstrap import BootstrapResult
from ..contracts.scene import SceneConfig, SceneObject, Transform
from ..contracts.turn import SceneEditPlan
from ..contracts.task_intent import TaskEntity
from ..grounding.scene_relation_resolver import SceneRelationResolver
from .asset_resolver import AssetResolver


class SceneBootstrapper:
    def __init__(self, assets, defaults, *, robot="ur5e", seed=0):
        self.assets, self.defaults, self.robot, self.seed = assets, defaults, robot, seed
        self.resolver = AssetResolver(assets)

    def prepare(self, turn, *, scene_id):
        if turn.status != "accepted" or turn.turn_kind not in {"robot_task", "scene_edit"}:
            raise ValueError("scene_required")
        if turn.turn_kind == "robot_task":
            entities, relations = turn.task_intent.entities, turn.task_intent.spatial_relations
        else:
            plan = turn.scene_edit
            if not isinstance(plan, SceneEditPlan):
                target = TaskEntity(entity_id="edit_target", semantic_name=plan.semantic_name,
                                    category=plan.category, count=plan.count,
                                    quantity_mode="all" if plan.count > 1 else "single")
                values = {"target":target.entity_id}
                entities = [target]
                if plan.reference:
                    # Legacy name-only references can be completed only by a
                    # unique catalog name/alias, never guessed from a category.
                    model = self.resolver.resolve(TaskEntity(entity_id="edit_reference", semantic_name=plan.reference,
                                                              category="unspecified"), infer_category=True).model
                    entities.append(TaskEntity(entity_id="edit_reference", semantic_name=plan.reference, category=model.category))
                    values["reference"] = "edit_reference"
                plan = SceneEditPlan(entities=entities, operations=[plan.model_copy(update=values)])
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
        table_model = self.assets.get_model_property(self.defaults.table_asset_id)
        table = SceneObject(scene_object_id=self.defaults.table_object_id, asset_id=table_model.asset_id,
                            semantic_name=table_model.semantic_name, category=table_model.category,
                            transform=Transform(position=self.defaults.table_position))
        if table_model.aabb_m:
            top = table.transform.position[2] + table_model.aabb_m[5]
        elif table_model.asset_id in self.assets.metadata.center_origin_assets:
            top = table.transform.position[2] + table_model.dimensions_m[2] / 2
        else:
            raise ValueError("bootstrap_origin_metadata_missing: table")
        if table_model.aabb_m:
            table_bounds = [table.transform.position[i] + table_model.aabb_m[i] for i in (0,1)]
            table_upper = [table.transform.position[i] + table_model.aabb_m[i+3] for i in (0,1)]
        else:
            table_bounds = [table.transform.position[i] - table_model.dimensions_m[i]/2 for i in (0,1)]
            table_upper = [table.transform.position[i] + table_model.dimensions_m[i]/2 for i in (0,1)]
        if any(self.defaults.workspace_min[i] < table_bounds[i] or self.defaults.workspace_max[i] > table_upper[i] for i in (0,1)):
            raise ValueError("bootstrap_workspace_outside_support")
        specs, candidates, bindings = [], {}, {}
        assumptions = ["source=system_default: tabletop grid placement; x right, y front, z up"]
        if self.assets.metadata.demo_assets:
            assumptions.append("demo_assets: metadata only; no real mesh or rendered material")
        for entity in entities:
            binding = self.resolver.resolve(entity)
            model = binding.model
            bindings[entity.entity_id] = model.asset_id
            assumptions.extend(binding.assumptions)
            count = entity.count
            if entity.all_available:
                count = self.defaults.initial_counts.get(model.semantic_name)
                if count is None:
                    raise ValueError("bootstrap_quantity_unspecified: " + model.semantic_name)
                assumptions.append(f"source=system_default: {model.semantic_name} count={count}")
            if model.asset_id == table.asset_id:
                if count != 1:
                    raise ValueError("bootstrap_layout_failed: multiple base tables unsupported")
                candidates[entity.entity_id] = [table.scene_object_id]
                continue
            if model.aabb_m:
                if any(abs(model.aabb_m[i] + model.aabb_m[i+3]) > 1e-6 for i in (0, 1)):
                    raise ValueError("bootstrap_origin_metadata_unsupported: offset xy origin")
                bottom = model.aabb_m[2]
            elif model.asset_id in self.assets.metadata.center_origin_assets:
                bottom = -model.dimensions_m[2] / 2
            else:
                raise ValueError("bootstrap_origin_metadata_missing: " + model.asset_id)
            candidates[entity.entity_id] = []
            for _ in range(count):
                object_id = f"{model.semantic_name}_{1+sum(s[0].semantic_name == model.semantic_name for s in specs):02d}"
                if object_id == table.scene_object_id:
                    raise ValueError("bootstrap_object_id_collision")
                props = {**binding.properties, "aliases": [entity.semantic_name, *entity.aliases], "support": table.scene_object_id}
                obj = SceneObject(scene_object_id=object_id, asset_id=model.asset_id, semantic_name=model.semantic_name,
                                  category=model.category, transform=Transform(position=(0, 0, top-bottom)), properties=props)
                specs.append((obj, model))
                candidates[entity.entity_id].append(object_id)
        rng = random.Random(self.seed)
        xmin, ymin = self.defaults.workspace_min
        xmax, ymax = self.defaults.workspace_max
        # Bounded deterministic candidate search, never reduce requested counts.
        for attempt in range(self.defaults.max_attempts):
            placed = []
            for obj, model in specs:
                dx, dy, _ = model.dimensions_m
                if dx >= xmax-xmin or dy >= ymax-ymin:
                    raise ValueError("bootstrap_layout_failed: object exceeds workspace")
                x, y = rng.uniform(xmin+dx/2, xmax-dx/2), rng.uniform(ymin+dy/2, ymax-dy/2)
                if any(abs(x-p.transform.position[0]) < (dx+m.dimensions_m[0])/2+self.defaults.clearance_m
                       and abs(y-p.transform.position[1]) < (dy+m.dimensions_m[1])/2+self.defaults.clearance_m for p,m in placed):
                    break
                placed.append((obj.model_copy(update={"transform": obj.transform.model_copy(update={"position": (x,y,obj.transform.position[2])})}), model))
            if len(placed) != len(specs):
                continue
            scene = SceneConfig(scene_id=scene_id, robot=self.robot, objects=[table, *[p for p,_ in placed]])
            by_id = {o.scene_object_id:o for o in scene.objects}
            valid = True
            for entity in entities:
                selection = []
                for rel in initial:
                    if rel.subject != entity.entity_id:
                        continue
                    ref = rel.reference
                    if ref:
                        if len(candidates.get(ref, [])) != 1:
                            raise ValueError("bootstrap_relation_unsupported: reference is not unique")
                        ref = candidates[ref][0]
                    selection.append(rel.model_copy(update={"reference": ref, "scope": "selection"}))
                matches = SceneRelationResolver().resolve([by_id[i] for i in candidates[entity.entity_id]], selection, scene, entity.entity_id)
                required = 1 if entity.quantity_mode == "candidate_pool" else len(candidates[entity.entity_id])
                if len(matches) != required:
                    valid = False
                    break
            if valid:
                return BootstrapResult(scene=scene, entity_candidates=candidates, asset_bindings=bindings,
                                       assumptions=list(dict.fromkeys(assumptions)))
        raise ValueError("bootstrap_layout_failed: exhausted configured attempts")
