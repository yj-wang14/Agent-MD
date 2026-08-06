# Force Field KSpace Warning Audit

## Warning

LAMMPS warning text:

```text
Neighbor exclusions used with KSpace solver may give inconsistent Coulombic energies
```

## Where It Comes From

The generated equilibration, initial GCMC, and continuation inputs combine long-range electrostatics with explicit neighbor exclusions:

```lammps
kspace_style pppm 1.0e-4
neigh_modify exclude group clay_lower clay_lower
neigh_modify exclude group clay_upper clay_upper
```

The workflow also uses bonded special scaling and SHAKE constraints:

```lammps
special_bonds lj/coul 0.0 0.0 0.5
fix wshake water shake 1.0e-4 50 0 b 1 a 1 mol h2omol
```

The warning is expected when `neigh_modify exclude` is used with a KSpace solver because excluded real-space pair interactions are not automatically matched by equivalent long-range corrections. In this workflow, the exclusions are intended only to suppress intra-sheet nonbonded interactions inside the rigid clay sheets.

## Current Assumptions

- Clay sheets are normalized to molecule IDs `1` and `2` and run with `fix rigid/nve molecule`.
- The exclusions are group-based intra-sheet clay exclusions: `clay_lower` with itself and `clay_upper` with itself.
- SPC/E water is inserted with `molecule h2omol ...` and constrained by `fix shake` using bond type `1` and angle type `1`.
- `special_bonds lj/coul 0.0 0.0 0.5` is used consistently across equilibration and GCMC inputs.
- The inserted water molecule template must carry the intended atom, bond, angle, charge, and special-list behavior for the converted type IDs.

## Validated Run Impact

This warning did not stop the validated RH=0.9 workflow: the pre-GCMC equilibration, 2,000,000-step initial RH=0.9 segment, and two 1,000,000-step continuation segments completed without LAMMPS `ERROR`, lost atoms, PPPM out-of-range atoms, SHAKE failure, NaN, or dangerous neighbor builds.

Successful numerical completion does not prove the force-field treatment is physically consistent. The warning remains a force-field audit item, especially because KSpace consistency depends on how intramolecular and excluded Coulomb terms are represented.

## Recommendation

Do not change force-field settings in this cleanup pass. Treat the warning as non-blocking for workflow validation but unresolved for publication-quality production.

## TODO

- Check ClayFF plus SPC/E `special_bonds` convention against accepted LAMMPS implementations.
- Check inserted water molecule special lists and whether they match the intended intramolecular exclusions.
- Check whether water intramolecular Coulomb interactions are treated as intended with SHAKE and KSpace.
- Review whether group-based clay intra-sheet exclusions are the correct ClayFF representation under PPPM.
- Compare the generated inputs with accepted ClayFF/SPC/E LAMMPS setups before publication.
