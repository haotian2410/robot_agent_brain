from ..contracts.camera import CameraFrame
from ..models.vision_grounding import VisionEntity, VisionGroundingOutput

def _iou(left, right):
    ly1, lx1, ly2, lx2 = left
    ry1, rx1, ry2, rx2 = right
    iy1, ix1, iy2, ix2 = max(ly1, ry1), max(lx1, rx1), min(ly2, ry2), min(lx2, rx2)
    area = max(0, iy2 - iy1) * max(0, ix2 - ix1)
    union = (ly2-ly1)*(lx2-lx1) + (ry2-ry1)*(rx2-rx1) - area
    return area / union if union else 0.0

class VisionFallbackGrounder:
    def ground(self, frame: CameraFrame, output: VisionGroundingOutput, entities: list[VisionEntity]):
        by_entity = {item.entity_id: item for item in entities}
        result = {}
        for detection in output.detections:
            if detection.entity not in by_entity:
                continue
            matches = [(box.scene_object_id, _iou(detection.bbox, box.bbox)) for box in frame.instance_boxes]
            matches = [item for item in matches if item[1] > 0]
            if not matches:
                raise ValueError("vision_grounding_scene_instance_missing")
            matches.sort(key=lambda item: item[1], reverse=True)
            if len(matches) > 1 and matches[0][1] == matches[1][1]:
                raise ValueError("vision_grounding_scene_instance_ambiguous")
            result[detection.entity] = matches[0][0]
        return result
