"""Component bootstrap with configured library resources and measured bounds."""
import random

from ..contracts.bootstrap import BootstrapResult
from ..contracts.scene import SceneConfig, SceneObject, SceneComponent, RobotDriverProperties
from ..contracts.spatial import ResolvedSelectionRelation
from ..grounding.scene_relation_resolver import SceneRelationResolver
from ..grounding.scene_reference_resolver import SceneReferenceResolver
from .asset_resolver import AssetResolver
from .geometry import world_bounds
from .scene_graph import WorldTransform, world_transform

IDENTITY = ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.))


def make_object(identifier, name, reference, position, *, category=None, support=None, driver=None, asset_type=None):
    components = [
        SceneComponent(component_type="Transform", properties={
            "position": list(position), "quaternion_xyzw": [0, 0, 0, 1],
            "scale": [1, 1, 1], "parent": None}),
        SceneComponent(component_type="MetadataRef", properties={"path": reference, **({"type": asset_type} if asset_type else {})}),
    ]
    if category is not None:
        components.append(SceneComponent(component_type="Semantic", properties={
            "semantic_name": name, "category": category, "support": support}))
    if driver is not None:
        components.append(SceneComponent(component_type="RobotDriver", properties=driver.model_dump(mode="json")))
    return SceneObject(object_id_in_scene=identifier, object_name_in_scene=name, components=components)


class SceneBootstrapper:
    def __init__(self, assets, defaults, *, robot="ur5e", seed=0, table_metadata_ref=None,
                 robot_metadata_ref=None, robot_driver=None, template_scene=None, aliases=None, category_aliases=None,
                 default_scene_edit_assets=None, scene_reference_catalog=None):
        self.assets, self.defaults, self.robot, self.seed = assets, defaults, robot, seed
        self.table_ref, self.robot_ref = table_metadata_ref, robot_metadata_ref
        self.driver = robot_driver
        self.template_scene = template_scene
        self.robot_profile = None
        self.resolver = AssetResolver(assets, aliases=aliases, category_aliases=category_aliases)
        self.default_scene_edit_assets = dict(default_scene_edit_assets or {})
        self.scene_reference_catalog = scene_reference_catalog

    def for_profile(self, profile):
        from .component_access import SceneIndex
        if "table" not in profile.platform_roles:
            raise ValueError("bootstrap_profile_table_role_missing")
        table_id = profile.platform_roles["table"]
        index = SceneIndex(profile.template)
        robot_id = next(iter(profile.setup.arms.values())).robot_object_id
        template = profile.template.model_copy(update={"objects": [obj.model_copy(deep=True) for obj in profile.template.objects
                                                                   if obj.object_id_in_scene in profile.platform_object_ids]})
        template = SceneConfig.model_validate(template.model_dump())
        bootstrap = SceneBootstrapper(self.assets, self.defaults.model_copy(update={"table_object_id": table_id, "robot_object_id": robot_id}),
            robot=profile.v2_robot or profile.setup.profile_id, seed=self.seed,
            table_metadata_ref=index.metadata_ref(table_id), robot_metadata_ref=index.metadata_ref(robot_id),
            robot_driver=index.robot_driver(robot_id), template_scene=template,
            aliases=self.resolver.aliases, category_aliases=self.resolver.category_aliases)
        bootstrap.default_scene_edit_assets = dict(self.default_scene_edit_assets)
        bootstrap.scene_reference_catalog = self.scene_reference_catalog
        bootstrap.robot_profile = profile
        return bootstrap

    def prepare(self, turn, *, scene_id):
        if turn.status != "accepted" or turn.turn_kind not in {"robot_task", "scene_edit"}:
            raise ValueError("scene_required")
        if self.table_ref is None or self.robot_ref is None:
            raise ValueError("bootstrap_config_missing: configure table/robot MetadataRef")
        if self.driver is None and self.template_scene is None:
            # A template scene carries the robot's own RobotDriver component, so the configured
            # default driver is only needed when the table and robot are built from nothing here.
            raise ValueError("bootstrap_config_missing: configure RobotDriver for a bootstrap without a template scene")
        driver = (RobotDriverProperties.model_validate(self.driver.model_dump() if hasattr(self.driver, "model_dump") else self.driver)
                  if self.driver is not None else None)
        if turn.turn_kind == "robot_task":
            entities, relations = turn.task_intent.entities, turn.task_intent.spatial_relations
        else:
            plan = turn.scene_edit
            if all(op.operation in {"remove", "replace"} for op in plan.operations):
                raise ValueError("scene_required: cannot create objects only to remove them")
            defined, needed = set(), set()
            entity_ids = {entity.entity_id for entity in plan.entities}
            for op in plan.operations:
                # Only task entities participate in bootstrap grounding.  A
                # reference such as ``table`` is resolved later through the
                # scene-reference catalog and must not be sent to AssetResolver.
                if op.reference and op.reference in entity_ids and op.reference not in defined:
                    needed.add(op.reference)
                if op.operation == "add":
                    if op.target in needed:
                        raise ValueError("bootstrap_entity_lifecycle_conflict")
                    defined.add(op.target)
                elif op.target not in defined:
                    needed.add(op.target)
            while True:
                refs = {r.reference for r in plan.relations if r.subject in needed and r.reference
                        and r.reference in entity_ids}
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
        table_model = (self.assets.resolve(self.table_ref, "model") if self.template_scene else self.assets.resolve(self.table_ref))
        if self.template_scene:
            self.assets.resolve(self.robot_ref, "robot")
        else:
            self.assets.resolve(self.robot_ref)
        if self.template_scene is not None:
            base_objects = [obj.model_copy(deep=True) for obj in self.template_scene.objects]
            table_candidates = [obj for obj in base_objects if any(
                c.component_type == "MetadataRef" and c.properties.get("path") == self.table_ref
                and c.properties.get("type") == "model" for c in obj.components)]
            robot_candidates = [obj for obj in base_objects if any(
                c.component_type == "MetadataRef" and c.properties.get("path") == self.robot_ref
                and c.properties.get("type") == "robot" for c in obj.components)]
            if self.robot_profile is not None:
                self.robot_profile.validate_scene(self.template_scene)
                selected = {arm.robot_object_id for arm in self.robot_profile.setup.arms.values()}
                robot_candidates = [obj for obj in base_objects if obj.object_id_in_scene in selected]
                for obj in base_objects:
                    for component in obj.components:
                        if component.component_type == "MetadataRef":
                            self.assets.resolve(component.properties["path"], component.properties.get("type"))
            if len(table_candidates) != 1 or not robot_candidates or (self.robot_profile is None and len(robot_candidates) != 1):
                raise ValueError("bootstrap_template_platform_objects_missing")
            table_id, robot_id = table_candidates[0].object_id_in_scene, robot_candidates[0].object_id_in_scene
            table = table_candidates[0]
            robot = robot_candidates[0]
            base_max = max((obj.object_id_in_scene for obj in base_objects), default=-1)
        else:
            base_objects = []
            table_id, robot_id = self.defaults.table_object_id, self.defaults.robot_object_id
            table = make_object(table_id, "table", self.table_ref, self.defaults.table_position,
                                category="surface")
            robot = make_object(robot_id, self.robot, self.robot_ref, self.defaults.robot_position,
                                driver=driver)
            base_max = max(table_id, robot_id)
        reference_resolver = SceneReferenceResolver(self.scene_reference_catalog,
                                                    table_metadata_ref=self.table_ref)
        if turn.turn_kind == "scene_edit":
            for operation in plan.operations:
                if operation.reference and operation.reference not in entity_ids:
                    reference_resolver.resolve(operation.reference, entities=plan.entities,
                                               scene=self.template_scene,
                                               default_surface_id=table_id,
                                               scene_basis=plan.scene_basis)
        table_transform = (world_transform(self.template_scene, table_id)
                           if self.template_scene is not None
                           else WorldTransform(self.defaults.table_position, IDENTITY))
        table_low, table_high = world_bounds(table_model, table_transform)
        if any(self.defaults.workspace_min[i] < table_low[i] or self.defaults.workspace_max[i] > table_high[i] for i in (0, 1)):
            raise ValueError("bootstrap_workspace_outside_support")
        specs, candidates, bindings = [], {}, {}
        assumptions = ["source=system_default: tabletop placement; x right, y front, z up"]
        next_id = base_max + 1
        for entity in entities:
            binding = AssetResolver(self.assets, aliases=self.resolver.aliases,
                                    category_aliases=self.resolver.category_aliases,
                                    default_refs=self.default_scene_edit_assets).resolve(
                                        entity, allow_default=turn.turn_kind == "scene_edit")
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
                from .geometry import local_bounds
                low, high = local_bounds(model)
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
                                          position, category=category, support=table_id,
                                          asset_type=model.asset_type if self.template_scene else None))
                bounds.append(box)
            if len(placed) != len(specs):
                continue
            scene = SceneConfig(scene_schema_version=1, scene_version=1, scene_id=scene_id,
                                scene_name=(self.template_scene.scene_name if self.template_scene else "Generated task scene"),
                                objects=[*base_objects, *placed] if base_objects else [table, robot, *placed])
            by_id = {o.object_id_in_scene: o for o in scene.objects}
            valid = True
            for entity in entities:
                selection = []
                for rel in initial:
                    if rel.subject != entity.entity_id:
                        continue
                    ref = None
                    if rel.reference is not None:
                        if rel.reference in candidates:
                            if len(candidates[rel.reference]) != 1:
                                raise ValueError("bootstrap_relation_unsupported: reference is not unique")
                            ref = candidates[rel.reference][0]
                        else:
                            resolved = reference_resolver.resolve(
                                rel.reference, entities=plan.entities if turn.turn_kind == "scene_edit" else entities,
                                scene=scene, default_surface_id=table_id,
                                scene_basis=plan.scene_basis if turn.turn_kind == "scene_edit" else "current")
                            if resolved.object_id is None:
                                raise ValueError("bootstrap_relation_unsupported: reference is not bound")
                            ref = resolved.object_id
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
