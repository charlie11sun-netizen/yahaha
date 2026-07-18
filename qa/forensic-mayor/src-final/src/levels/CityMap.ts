import type { Cell, CityMapDefinition } from "../content/CityTypes";

function cells(points: readonly (readonly [number, number])[]): readonly Cell[] {
  return Object.freeze(points.map(([x, y]) => Object.freeze({ x, y })));
}

function boundaryCells(): readonly Cell[] {
  const result: Cell[] = [];
  for (let x = 0; x < 24; x += 1) {
    result.push(Object.freeze({ x, y: 0 }), Object.freeze({ x, y: 13 }));
  }
  for (let y = 1; y < 13; y += 1) {
    result.push(Object.freeze({ x: 0, y }), Object.freeze({ x: 23, y }));
  }
  return Object.freeze(result);
}

export const CITY_MAP: CityMapDefinition = Object.freeze({
  cols: 24,
  rows: 14,
  cellWidth: 1280 / 24,
  cellHeight: 720 / 14,
  maxBuildings: 160,
  regions: Object.freeze([
    Object.freeze({ id: "sunny_meadows", name: "暖阳住宅草坪", kind: "低污染住宅规划区", x: 1, y: 1, width: 8, height: 6 }),
    Object.freeze({ id: "civic_start", name: "市政起步区", kind: "教学与初始道路周边建设区", x: 9, y: 1, width: 7, height: 6 }),
    Object.freeze({ id: "utility_buffer", name: "东部设施缓冲地", kind: "适合电厂和供水设施的远郊工程区", x: 16, y: 1, width: 7, height: 6 }),
    Object.freeze({ id: "south_expansion", name: "南部扩建平原", kind: "中后期综合城市扩建区", x: 1, y: 7, width: 22, height: 6 }),
  ]),
  boundaryCells: boundaryCells(),
  reservedTreeCells: cells([
    [2, 2], [6, 2], [3, 5], [18, 2], [21, 4], [2, 10], [6, 11], [18, 10], [21, 11],
  ]),
  starterRoadCells: cells([
    [8, 7], [9, 7], [10, 7], [11, 7], [12, 7], [13, 7], [14, 7], [15, 7],
  ]),
  paths: Object.freeze([
    Object.freeze({
      id: "starter_road",
      points: cells([[8, 7], [9, 7], [10, 7], [11, 7], [12, 7], [13, 7], [14, 7], [15, 7]]),
    }),
    Object.freeze({
      id: "tutorial_utility_route",
      points: cells([[15, 7], [16, 7], [17, 7], [18, 7], [18, 6], [18, 5]]),
    }),
    Object.freeze({
      id: "tutorial_residential_route",
      points: cells([[8, 7], [7, 7], [6, 7], [6, 6], [6, 5]]),
    }),
  ]),
  points: Object.freeze([
    Object.freeze({ id: "mayor_cursor_spawn", kind: "spawn", x: 11, y: 7 }),
    Object.freeze({ id: "first_power_hint", kind: "objective", x: 18, y: 3 }),
    Object.freeze({ id: "first_water_hint", kind: "objective", x: 20, y: 7 }),
    Object.freeze({ id: "first_home_hint", kind: "objective", x: 5, y: 5 }),
    Object.freeze({ id: "first_shop_hint", kind: "objective", x: 10, y: 5 }),
    Object.freeze({ id: "pollution_warning_marker", kind: "hazard", x: 16, y: 3 }),
    Object.freeze({ id: "milestone_banner_origin", kind: "item", x: 12, y: 2 }),
    Object.freeze({ id: "city_hall_goal", kind: "exit", x: 12, y: 10 }),
  ]),
});
