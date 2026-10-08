import math
from ..models.vision_grounding import VisionEntity

def _iou(left, right):
    y1, x1, y2, x2 = left
    v1, u1, v2, u2 = right
    overlap = max(0, min(y2,v2)-max(y1,v1)) * max(0, min(x2,u2)-max(x1,u1))
    union = (y2-y1)*(x2-x1)+(v2-v1)*(u2-u1)-overlap
    return overlap / union if union else 0

class VisionFallbackGrounder:
    def __init__(self, min_iou=0.5):
        self.min_iou = min_iou

    def resolve(self, entity, candidates, scene, frame, provider):
        if (frame.scene_id, frame.scene_version) != (scene.scene_id, scene.scene_version):
            raise ValueError("camera_frame_scene_mismatch")
        if frame.rgb is None or not frame.instance_boxes:
            raise ValueError("vision_grounding_scene_instance_missing")
        known = {o.object_id_in_scene for o in scene.objects}
        if any(b.scene_object_id not in known for b in frame.instance_boxes):
            raise ValueError("vision_grounding_unknown_scene_instance")
        output = provider.detect(frame, [VisionEntity(entity_id=entity.entity_id, semantic_name=entity.semantic_name)])
        eligible = {o.object_id_in_scene for o in candidates}
        result = []
        for detection in output.detections:
            if detection.entity != entity.entity_id:
                raise ValueError("vision_grounding_unknown_entity")
            matches = sorted([(_iou(detection.bbox, b.bbox), b.scene_object_id) for b in frame.instance_boxes], reverse=True)
            if not matches or matches[0][0] < self.min_iou:
                raise ValueError("vision_grounding_scene_instance_missing")
            if len(matches) > 1 and math.isclose(matches[0][0], matches[1][0], abs_tol=1e-9):
                raise ValueError("vision_grounding_scene_instance_ambiguous")
            object_id = matches[0][1]
            if object_id not in eligible:
                raise ValueError("vision_grounding_candidate_mismatch")
            if object_id not in result:
                result.append(object_id)
        required = entity.count if entity.quantity_mode == "all" else 1
        if entity.all_available:
            required = len(candidates)
        if len(result) != required:
            raise ValueError("vision_grounding_ambiguous")
        return result
