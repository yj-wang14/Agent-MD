# Water Partition And Basal Proxy Audit

## Scope

This audit covers the generated LAMMPS monitor definitions in `mtagent/run_initial.py` and `mtagent/generate_gcmc_input.py`. It does not change simulation behavior.

## Definitions Used

The generated inputs define the total water count from the `water` group:

```lammps
variable nwater_atoms equal count(water)
variable nwater_mol   equal count(water)/3.0
```

The clay sheet z positions are recomputed from the current clay groups:

```lammps
compute zlow clay_lower reduce ave z
compute zup  clay_upper reduce ave z

variable zlow_now equal c_zlow
variable zup_now  equal c_zup

variable basal_proxy equal v_zup_now-v_zlow_now
variable zcenter equal 0.5*(v_zup_now+v_zlow_now)
```

Water partitioning uses atom-style variables based on the current oxygen z coordinate and the current sheet average z positions:

```lammps
variable is_bottom_ow atom (type==8)&&(z<v_zlow_now)
variable is_inter_ow  atom (type==8)&&(z>=v_zlow_now)&&(z<=v_zup_now)
variable is_top_ow    atom (type==8)&&(z>v_zup_now)

compute nw_bottom all reduce sum v_is_bottom_ow
compute nw_inter  all reduce sum v_is_inter_ow
compute nw_top    all reduce sum v_is_top_ow

variable nwat_bottom equal c_nw_bottom
variable nwat_inter  equal c_nw_inter
variable nwat_top    equal c_nw_top
variable nwat_ext    equal v_nwat_bottom+v_nwat_top
```

The monitored columns are appended with:

```lammps
fix mon all ave/time ... &
  v_nwater_mol v_nwat_inter v_nwat_bottom v_nwat_top v_nwat_ext &
  v_basal_proxy v_zcenter ... &
  append monitor_gcmc_<rh>.dat
```

## Dynamic Versus Static Behavior

- `nwater_inter` is dynamic. It is counted from water oxygen atoms whose current `z` coordinate lies between `v_zlow_now` and `v_zup_now`.
- `nwater_ext` is dynamic. It is the sum of dynamically counted bottom and top oxygen counts outside those current sheet boundaries.
- `basal_proxy` is dynamic. It is the current difference between the average z positions of `clay_upper` and `clay_lower`.
- No fixed interlayer or external `region` is used for these monitor counts. The only fixed region in this part of the workflow is the configured GCMC insertion region.

## Risks

The current definitions follow translation of the clay sheets in z because they reference current sheet averages. That is appropriate for the present rigid-clay setup, where each clay sheet is constrained as one rigid body with z translation allowed and x/y motion and rotation disabled.

Remaining approximation: `basal_proxy` is an average-z sheet separation, not a crystallographic basal spacing derived from a plane fit or lattice repeat. This should be stable for non-rotating rigid sheets, but it would become less reliable if sheet tilt, bending, large wrapping events, or non-rigid clay motion were introduced. Water partitioning also uses oxygen atoms only, so molecules crossing a boundary are classified by oxygen position.

## Recommendation

Keep as-is for the validated workflow. The definitions are dynamically tied to clay sheet z positions and are consistent with the current rigid, non-rotating clay constraints. Improve later if the model allows clay rotation/deformation, if periodic wrapping of clay sheets becomes significant, or if publication analysis needs a stricter basal-spacing definition.
