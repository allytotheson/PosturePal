# Vendored VQF

Unmodified official sources from [dlaidig/vqf, tag v2.1.2](https://github.com/dlaidig/vqf/tree/v2.1.2).
`vqf.hpp` and `vqf.cpp` are from `vqf/cpp/`; `VQF-LICENSE.txt` is upstream
`LICENSES/MIT.txt`. Per-file SPDX copyright notices identify Daniel Laidig (2021).
Retain both those notices and the MIT license when redistributing.

SHA-256:

```text
ef15c074bce16adb76e7f191970ea589bc6d7ce01027130e5233041c0e11eb24  vqf.hpp
fb035248ebeccc16897476c7afca5e912f3ad77f0faebd16ff4d5f94b44c614b  vqf.cpp
```

No Arduino Library Manager VQF wrapper is needed. Arduino compiles the `.cpp`
alongside the sketch. Default `vqf_real_t = double` is used throughout; no
`VQF_SINGLE_PRECISION` or `VQF_NO_MOTION_BIAS_ESTIMATION` defines are set.
Build with `-O2`, not the nRF52 core's default `-Ofast`: VQF uses NaNs internally
to mark uninitialized low-pass filter state. See [setup](../../docs/SETUP.md).
