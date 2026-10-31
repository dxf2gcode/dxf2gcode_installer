"""Pure calculation of the axial depth sequence for one toolpath."""


def calculate_depth_passes(start_mill_depth, slice_depth, final_mill_depth,
                           single_pass=False):
    """Return the ordered Z depths used to mill a shape.

    The first pass is one slice below the workpiece top, followed by slices to
    the final depth. ``single_pass`` is used for DXF output and non-repeated
    drill moves, which start directly at the final depth.
    """
    max_slice = -abs(slice_depth)
    initial_depth = start_mill_depth + max_slice
    if single_pass:
        initial_depth = final_mill_depth

    depths = [initial_depth]
    current_depth = initial_depth
    while current_depth > final_mill_depth and max_slice < 0.0:
        current_depth = current_depth + max_slice
        if current_depth < final_mill_depth:
            current_depth = final_mill_depth
        depths.append(current_depth)
    return depths
