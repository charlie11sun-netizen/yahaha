# 语义驱动的雪碧图生成管线

生成图像不再直接作为运行时雪碧图合同。`contract_gate` 冻结设计契约后派生
`sprite_demand_manifest` 只读视图（`asset_processing` / `asset_generation` 只消费，
不重新解读设计），每一帧都有 `semantic_id`、`frame_id`、状态、是否必需、
动画分组、anchor 和运行时消费者。

## 数据流

```text
DesignContract（contract_gate 冻结后派生视图）
  -> SpriteDemandManifest
  -> BatchSpec（只混合同对象/同风格帧）
  -> provider batch image
  -> cell slicing + FrameAudit
  -> （可选）VLM 语义评审 + 单格重生成
  -> atlas / spritesheet manifest
  -> runtime consumer annotation
  -> scene QA
```

`backend/app/services/sprite_pipeline.py` 提供以下能力：

- `build_sprite_demand_manifest()`：把建筑等级、角色状态、道具状态转换成语义帧；
  `residential.level_3` 不会退化成 `entity_2`。
- `build_batch_specs()`：默认只生成必需帧，并优先使用 2×2、2×4、4×4 批次；
  程序化变体不会创建新的模型请求。
- `audit_frame()` / `audit_batch()`：检查尺寸、透明背景、cell 边界、主体数量、
  anchor 稳定性、风格提示和消费者覆盖率。多主体帧会记录
  `expected_object_count=1` 与 `detected_object_count>1`。
- `build_cell_regeneration_specs()`：帧审计失败后只重画失败格（锁定已通过格的局部复审），
  重试上限 `ASSET_FRAME_AUDIT_MAX_RETRIES`。
- `pack_atlas()` 和 `apply_programmatic_variant()`：程序负责打包与高亮、受伤、阴影、
  禁用等简单变体。

管线的规划 / 复用 / 评审 / 后处理环节拆分在同层服务中：`asset_planning.py`（按契约需求排批次与预算）、
`asset_reuse.py`（repair/replan 后按 prompt hash 逐 key 复用，仅增量重生成失效 key）、
`asset_semantic_review.py`（可选 VLM 语义评审，`ASSET_SEMANTIC_REVIEW_*` 开关，先看整张原图再考虑单格重画）、
`asset_postprocess.py`（切帧与透明处理）。图像修复调用有预算上限（`ASSET_REPAIR_MAX_IMAGE_CALLS`）；
整体必需帧覆盖率达 `ASSET_RELEASE_COVERAGE_FLOOR`（默认 0.8）时可带伤放行，
主图像供应商持续 5xx 时走 `ASSET_IMAGE_FALLBACK_*` 兜底提供商链。

生成资产仍保留旧的 `frames` 字段以兼容已有 Phaser 项目，但新增：

- sheet 级 `semantic_frames`、`frame_audit`、`frame_semantics`；
- manifest 级 `runtime_manifest` 与 `metrics.required_asset_coverage`；
- 透明 `bonus_*` 只是未进入正式 manifest 的空槽，不是可引用素材。

新运行时代码应使用：

```ts
const ref = spriteFrame("residential.level_3");
if (ref) this.add.sprite(x, y, ref.key, ref.index);
```

不要依赖 `sheet frame index 15`。生成后的运行时消费会被再次扫描，未引用的必需帧
会进入 QA 错误，目标指标是 `required_asset_coverage = 1.0` 和
`unused_required_frame = 0`。
