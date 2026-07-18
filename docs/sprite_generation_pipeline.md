# 语义驱动的雪碧图生成管线

生成图像不再直接作为运行时雪碧图合同。`asset_processing` 先从设计合同建立
`sprite_demand_manifest`，每一帧都有 `semantic_id`、`frame_id`、状态、是否必需、
动画分组、anchor 和运行时消费者。

## 数据流

```text
DesignContract
  -> SpriteDemandManifest
  -> BatchSpec（只混合同对象/同风格帧）
  -> provider batch image
  -> cell slicing + FrameAudit
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
- `pack_atlas()` 和 `apply_programmatic_variant()`：程序负责打包与高亮、受伤、阴影、
  禁用等简单变体。

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
