from typing import List, TypedDict, Tuple

class ExerciseData(TypedDict):
    exercise: str
    sets: List[Tuple[int, float]]
    volume: int