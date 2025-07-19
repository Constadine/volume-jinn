import math
import requests
from typing import Any, Dict, List, Optional, TypedDict, Tuple

class ExerciseData(TypedDict):
    exercise: str
    sets: List[Tuple[int, float]]
    volume: int


class Hevy:
    def __init__(self, apikey):
        self.apikey = apikey
        self.all_workouts = {}
        self.all_exercises = {}

    # ----------------------------------
    # Fetching functions
    # ----------------------------------
    def fetch_first_page_of_data(self):
        url = "https://api.hevyapp.com/v1/workouts?page=1"
        headers = {
            "accept": "application/json",
            "api-key": self.apikey
        }
        response = requests.get(url=url, headers=headers)

        if response.status_code == 401:
            raise ValueError("Invalid API key – Hevy returned 401 Unauthorized")
        if not response.ok:
            raise RuntimeError(f"Hevy API error {response.status_code}: {response.text[:120]}")
        try:
            payload = response.json()
        except ValueError as e:
            raise RuntimeError("Hevy response was not JSON, check the key/network") from e

        return payload


    def get_all_workouts(self):
        data = self.fetch_first_page_of_data()

        all_workouts = set([ex['title'] for ex in [w for w in data['workouts']]])
        self.all_workouts = all_workouts
        return all_workouts
    

    def get_all_exercises(self):
        data = self.fetch_first_page_of_data()

        all_exercises = [[ex['title'] for ex in w['exercises']] for w in data['workouts']]
        unique_exercises = sorted(set(sum(all_exercises, [])))

        self.all_exercises = unique_exercises
        return unique_exercises
    
    
    def fetch_last_workout(self, workout_title: Optional[str] = None) -> dict:
        """
        Fetch the last workout from Hevy API.
        If workout_title is provided, returns the most recent workout with that title.
        Otherwise, returns the most recent workout.

        Parameters:
        -----------
        apikey : str
            Your Hevy API key.
        workout_title : Optional[str]
            Title of the workout to filter for.

        Returns:
        --------
        dict
            The workout data.
        """

        payload = self.fetch_first_page_of_data()

        if workout_title:
            filtered_workouts = [w for w in payload['workouts'] if w['title'] == workout_title]
            last_workout_data = filtered_workouts[0] if filtered_workouts else None
        else:
            last_workout_data = payload['workouts'][0] if payload['workouts'] else None

        return last_workout_data
    

    def get_exercise_last_data(self, exercise_name: str) -> dict:
        payload = self.fetch_first_page_of_data()

        if exercise_name not in self.all_exercises:
            return {'error':"Exercise not found in data"}
        else:
            for workout in payload['workouts']:
                for exercise in workout['exercises']:
                    if exercise['title'] == exercise_name:
                        return exercise


    def calculate_exercise_volume(self, exercise_data: List[dict]) -> int:
        total_volume = 0
        for s in exercise_data:
            total_volume += s['weight_kg'] * s['reps'] if s['weight_kg'] and s['reps'] else 0
        
        return total_volume
    

    def structure_workout_data(self, workout_data: dict) -> List[ExerciseData]:
        schema = []
        for exercise in workout_data['exercises']:

            exercise_volume = self.calculate_exercise_volume(exercise['sets'])

            exercise_data = ExerciseData(
                exercise=exercise['title'],
                sets=[(s['reps'], s['weight_kg']) for s in exercise['sets']],
                volume=exercise_volume
            )
            schema.append(exercise_data)
        return schema
    
    
    def structure_exercise_data(self, exercise_data: dict) -> ExerciseData:

        exercise_volume = self.calculate_exercise_volume(exercise_data['sets'])

        structured_exercise = ExerciseData(
            exercise=exercise_data['title'],
            sets=[(s['reps'], s['weight_kg']) for s in exercise_data['sets']],
            volume=exercise_volume
            )

        return structured_exercise


    def optimize_weight_and_reps(
        self,
        base_sets: List[Tuple[int,float]],
        delta: float,
        avg_w: float,
        max_pct_wb: float,
        rep_floor: int,
        rep_cap:   int,
        exercise_name: str
    ) -> Optional[Dict[str,Any]]:
        """
        Try all 1.25kg bumps up to max_pct_wb * avg_w (or only 9kg for Leg Press),
        plus greedy-rep, to hit or slightly overshoot delta.
        """
        n = len(base_sets)
        # pick weight bump candidates
        if exercise_name == 'Leg Press Horizontal (Machine)':
            candidates = [9.0]
        else:
            max_w_inc = math.floor((avg_w*max_pct_wb)/1.25)*1.25
            candidates = [1.25 * i for i in range(1, int(max_w_inc/1.25)+1)]

        best = None
        for w_inc in candidates:
            # apply uniform weight bump
            bumped = [(r, w + w_inc) for r,w in base_sets]
            added_wvol = sum(r * w_inc for r,_ in base_sets)
            rem1 = delta - added_wvol
            if rem1 <= 0:
                return {
                    'w_inc': w_inc,
                    'bump_reps': [0]*n,
                    'total_added': added_wvol,
                    'overshoot': added_wvol - delta,
                    'final_sets': bumped
                }

            # greedy‐rep on bumped
            bump_r = [0]*n
            cap_extra = [rep_cap - r for r,_ in base_sets]
            # enforce rep_floor
            repfloor_added = 0.0
            for i,(r,w) in enumerate(bumped):
                if r < rep_floor:
                    need = min(rep_floor - r, cap_extra[i])
                    bump_r[i] = need
                    cap_extra[i] -= need
                    repfloor_added += need * w
            rem2 = rem1 - repfloor_added

            # one-rep at a time on heaviest
            added_rvol = repfloor_added
            order = sorted(range(n), key=lambda i: bumped[i][1], reverse=True)
            while rem2 > 0:
                for i in order:
                    if cap_extra[i] > 0:
                        bump_r[i] += 1
                        cap_extra[i] -= 1
                        added_rvol += bumped[i][1]
                        rem2 -= bumped[i][1]
                        break
                else:
                    break

            total_added = added_wvol + added_rvol
            overshoot = total_added - delta

            if any(bump_r) and overshoot >= -1e-6:
                final = [(r + bump_r[i], w + w_inc) for i,(r,w) in enumerate(base_sets)]
                cand = {
                    'w_inc': w_inc,
                    'bump_reps': bump_r,
                    'total_added': total_added,
                    'overshoot': overshoot,
                    'final_sets': final
                }
                if (best is None or
                    cand['overshoot'] < best['overshoot'] - 1e-6 or
                (abs(cand['overshoot']-best['overshoot'])<1e-6 and w_inc < best['w_inc'])):
                    best = cand

        return best

    def get_optimized_options(
        self,
        data: Dict[str,Any],
        volume_perc: float,
        max_pct_weight_bump: float = 0.10,
        rep_floor: int = 6,
        rep_cap:   int = 12
    ) -> Dict[str,Any]:
        orig = [(r,w) for r,w in data['sets'] if r is not None and w is not None]
        # handle exercises with no valid weight data
        if not orig:
            return {
                'delta':          0.0,
                'target_volume':  0.0,
                'phases':         [],
                'final_sets':     []
            }

        total_vol    = sum(r*w for r,w in orig)
        target_vol   = total_vol * (1 + volume_perc)
        delta        = target_vol - total_vol
        n            = len(orig)
        avg_w        = sum(w for _,w in orig) / n
        ex_name      = data.get('exercise','')
        result       = {'delta': delta, 'target_volume': target_vol, 'phases': []}

        # Phase 0: flatten >rep_cap
        lost = 0.0
        base_sets = []
        for r,w in orig:
            if r > rep_cap:
                lost += (r - rep_cap)*w
                base_sets.append((rep_cap,w))
            else:
                base_sets.append((r,w))
        vol0 = sum(r*w for r,w in base_sets)
        rem0 = target_vol - vol0
        result['phases'].append({
            'phase': 0,
            'lost_volume': lost,
            'base_sets': base_sets,
            'remaining': rem0
        })
        if rem0 <= 1e-6:
            result['final_sets'] = base_sets
            return result

        # Phase 1+2: optimized weight+reps
        best = self.optimize_weight_and_reps(
            base_sets, rem0, avg_w, max_pct_weight_bump,
            rep_floor, rep_cap, ex_name
        )
        if best:
            rem1 = rem0 - best['total_added']
            result['phases'].append({
                'phase': 1,
                'w_inc': best['w_inc'],
                'bump_reps': best['bump_reps'],
                'added_volume': best['total_added'],
                'overshoot': best['overshoot'],
                'final_sets': best['final_sets'],
                'remaining': rem1
            })
            if rem1 <= 1e-6:
                result['final_sets'] = best['final_sets']
                return result
            sets_so_far = best['final_sets']
        else:
            rem1 = rem0
            sets_so_far = base_sets

        # Phase 3: add new sets at rep_cap
        unit = rep_cap * avg_w
        full = int(rem1 // unit)
        rem3 = rem1 - full*unit
        plan = [(rep_cap, round(avg_w,2)) for _ in range(full)]
        if rem3 > 1e-6:
            rp = min(rep_cap, math.ceil(rem3/avg_w))
            plan.append((rp, round(avg_w,2)))
        added3 = sum(r*w for r,w in plan)
        final = sets_so_far + plan

        result['phases'].append({
            'phase': 2,
            'full_new_sets': full,
            'partial_new_set': plan[full:] or None,
            'added_volume': added3,
            'new_sets': final,
            'remaining': rem1 - added3
        })
        result['final_sets'] = final
        return result
