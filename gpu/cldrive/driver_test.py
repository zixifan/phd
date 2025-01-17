"""Unit tests for //gpu/cldrive/driver.py."""
import sys

import numpy as np
import pytest
from absl import app

from gpu.cldrive import data
from gpu.cldrive import driver
from gpu.cldrive import env
from gpu.cldrive import testlib


@pytest.mark.skip(reason="FIXME(cec)")
def test_empty_kernel():
  src = " kernel void A() {} "
  outputs = driver.DriveKernel(env.OclgrindOpenCLEnvironment(), src, [],
                               gsize=(1, 1, 1), lsize=(1, 1, 1))
  assert len(outputs) == 0


@pytest.mark.skip(reason="FIXME(cec)")
def test_simple():
  inputs = [[0, 1, 2, 3, 4, 5, 6, 7]]
  inputs_orig = [[0, 1, 2, 3, 4, 5, 6, 7]]
  outputs_gs = [[0, 2, 4, 6, 8, 10, 12, 14]]

  src = """
    kernel void A(global float* a) {
        const int x_id = get_global_id(0);

        a[x_id] *= 2.0;
    }
    """

  outputs = driver.DriveKernel(env.OclgrindOpenCLEnvironment(), src, inputs,
                               gsize=(8, 1, 1), lsize=(1, 1, 1))

  testlib.Assert2DArraysAlmostEqual(inputs, inputs_orig)
  testlib.Assert2DArraysAlmostEqual(outputs, outputs_gs)


@pytest.mark.skip(reason="FIXME(cec)")
def test_vector_input():
  inputs = [[0, 1, 2, 3, 0, 1, 2, 3], [2, 4]]
  inputs_orig = [[0, 1, 2, 3, 0, 1, 2, 3], [2, 4]]
  outputs_gs = [[0, 2, 4, 6, 0, 4, 8, 12], [2, 4]]

  src = """
    kernel void A(global int* a, const int2 b) {
        const int x_id = get_global_id(0);
        const int y_id = get_global_id(1);

        if (!y_id) {
            a[x_id] *= b.x;
        } else {
            a[get_global_size(0) + x_id] *= b.y;
        }
    }
    """

  outputs = driver.DriveKernel(env.OclgrindOpenCLEnvironment(), src, inputs,
                               gsize=(4, 2, 1), lsize=(1, 1, 1))

  testlib.Assert2DArraysAlmostEqual(inputs, inputs_orig)
  testlib.Assert2DArraysAlmostEqual(outputs, outputs_gs)

  # run kernel a second time with the previous outputs
  outputs2 = driver.DriveKernel(env.OclgrindOpenCLEnvironment(), src, outputs,
                                gsize=(4, 2, 1), lsize=(1, 1, 1))
  outputs2_gs = [[0, 4, 8, 12, 0, 16, 32, 48], [2, 4]]
  testlib.Assert2DArraysAlmostEqual(outputs2, outputs2_gs)


@pytest.mark.skip(reason="FIXME(cec)")
def test_syntax_error():
  src = "kernel void A(gl ob a l  i nt* a) {}"
  with testlib.DevNullRedirect():
    with pytest.raises(driver.OpenCLValueError):
      driver.DriveKernel(env.OclgrindOpenCLEnvironment(), src, [[]],
                         gsize=(1, 1, 1), lsize=(1, 1, 1))


@pytest.mark.skip(reason="FIXME(cec)")
def test_incorrect_num_of_args():
  src = "kernel void A(const int a) {}"
  # too many inputs
  with pytest.raises(ValueError):
    driver.DriveKernel(env.OclgrindOpenCLEnvironment(), src, [[1], [2], [3]],
                       gsize=(1, 1, 1), lsize=(1, 1, 1))

  # too few inputs
  with pytest.raises(ValueError):
    driver.DriveKernel(env.OclgrindOpenCLEnvironment(), src, [],
                       gsize=(1, 1, 1), lsize=(1, 1, 1))

  # incorrect input width (3 ints instead of one)
  with pytest.raises(ValueError):
    driver.DriveKernel(env.OclgrindOpenCLEnvironment(), src, [[1, 2, 3]],
                       gsize=(1, 1, 1), lsize=(1, 1, 1))


@pytest.mark.skip(reason="FIXME(cec)")
def test_timeout():
  # non-terminating kernel
  src = "kernel void A() { while (true) ; }"
  with pytest.raises(driver.Timeout):
    driver.DriveKernel(env.OclgrindOpenCLEnvironment(), src, [],
                       gsize=(1, 1, 1), lsize=(1, 1, 1), timeout=1)


@pytest.mark.skip(reason="FIXME(cec)")
def test_invalid_sizes():
  src = "kernel void A() {}"

  # invalid global size
  with pytest.raises(ValueError):
    driver.DriveKernel(env.OclgrindOpenCLEnvironment(), src, [],
                       gsize=(0, -4, 1), lsize=(1, 1, 1))

  # invalid local size
  with pytest.raises(ValueError):
    driver.DriveKernel(env.OclgrindOpenCLEnvironment(), src, [],
                       gsize=(1, 1, 1), lsize=(-1, 1, 1))


@pytest.mark.skip(reason="FIXME(cec)")
def test_gsize_smaller_than_lsize():
  src = "kernel void A() {}"
  with pytest.raises(ValueError):
    driver.DriveKernel(env.OclgrindOpenCLEnvironment(), src, [],
                       gsize=(4, 1, 1), lsize=(8, 1, 1))


@pytest.mark.skip(reason="FIXME(cec)")
def test_iterative_increment():
  src = "kernel void A(global int* a) { a[get_global_id(0)] += 1; }"

  d_cl, d_host = [np.arange(16)], np.arange(16)
  for _ in range(8):
    d_host += 1  # perform computation on host
    d_cl = driver.DriveKernel(env.OclgrindOpenCLEnvironment(), src, d_cl,
                              gsize=(16, 1, 1), lsize=(16, 1, 1))
    testlib.Assert2DArraysAlmostEqual(d_cl, [d_host])


@pytest.mark.skip(reason="FIXME(cec)")
def test_gsize_smaller_than_data():
  src = "kernel void A(global int* a) { a[get_global_id(0)] = 0; }"

  inputs = [[5, 5, 5, 5, 5, 5, 5, 5]]
  outputs_gs = [[0, 0, 0, 0, 5, 5, 5, 5]]

  outputs = driver.DriveKernel(env.OclgrindOpenCLEnvironment(), src, inputs,
                               gsize=(4, 1, 1), lsize=(4, 1, 1))

  testlib.Assert2DArraysAlmostEqual(outputs, outputs_gs)


@pytest.mark.skip(reason="FIXME(cec)")
def test_zero_size_input():
  src = "kernel void A(global int* a) {}"
  with pytest.raises(ValueError):
    driver.DriveKernel(env.OclgrindOpenCLEnvironment(), src, [[]],
                       gsize=(1, 1, 1), lsize=(1, 1, 1))


@pytest.mark.skip(reason="FIXME(cec)")
def test_comparison_against_pointer_warning():
  src = """
    kernel void A(global int* a) {
        int id = get_global_id(0);
        if (id < a) a += 1;
    }
    """

  driver.DriveKernel(env.OclgrindOpenCLEnvironment(), src, [[0]],
                     gsize=(1, 1, 1), lsize=(1, 1, 1))


@pytest.mark.skip(reason="FIXME(cec)")
def test_profiling():
  src = """
    kernel void A(global int* a, constant int* b) {
        const int id = get_global_id(0);
        a[id] *= b[id];
    }
    """

  inputs = [np.arange(16), np.arange(16)]
  outputs_gs = [np.arange(16) ** 2, np.arange(16)]

  with testlib.DevNullRedirect():
    outputs = driver.DriveKernel(env.OclgrindOpenCLEnvironment(), src, inputs,
                                 gsize=(16, 1, 1), lsize=(16, 1, 1),
                                 profiling=True)

  testlib.Assert2DArraysAlmostEqual(outputs, outputs_gs)


# TODO: Difftest against cl_launcher from CLSmith for a CLSmith kernel.

@pytest.mark.skip(reason="FIXME(cec)")
def test_data_unchanged():
  src = "kernel void A(global int* a, global int* b, const int c) {}"

  inputs = data.MakeRand(src, 16)
  outputs = driver.DriveKernel(env.OclgrindOpenCLEnvironment(), src, inputs,
                               gsize=(16, 1, 1), lsize=(1, 1, 1))

  testlib.Assert2DArraysAlmostEqual(outputs, inputs)


@pytest.mark.skip(reason="FIXME(cec)")
def test_data_zerod():
  # zero-ing a randomly initialized array
  src = "kernel void A(global int* a) { a[get_global_id(0)] = 0; }"

  inputs = data.MakeRand(src, 16)
  outputs = driver.DriveKernel(env.OclgrindOpenCLEnvironment(), src, inputs,
                               gsize=(16, 1, 1), lsize=(4, 1, 1))

  testlib.Assert2DArraysAlmostEqual(outputs, [np.zeros(16)])


@pytest.mark.skip(reason="FIXME(cec)")
def test_vector_input_switch():
  src = """
    kernel void A(global int2* a) {
        const int tid = get_global_id(0);

        const int tmp = a[tid].x;
        a[tid].x = a[tid].y;
        a[tid].y = tmp;
    }
    """

  inputs = data.MakeArange(src, 4)
  outputs_gs = [[1, 0, 3, 2, 5, 4, 7, 6]]

  outputs = driver.DriveKernel(env.make_env(), src, inputs, gsize=(4, 1, 1),
                               lsize=(4, 1, 1))

  testlib.Assert2DArraysAlmostEqual(outputs, outputs_gs)


def main(argv):  # pylint: disable=missing-docstring
  del argv
  sys.exit(pytest.main(
      [driver.__file__, __file__, "-v", "--doctest-modules"]))


if __name__ == "__main__":
  app.run(main)
