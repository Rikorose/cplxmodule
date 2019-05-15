import torch
import torch.nn.functional as F


class Cplx():
    __slots__ = ("_real", "_imag")

    def __new__(cls, real=0., imag=0.):
        if isinstance(real, cls):
            return real

        self = super().__new__(cls)
        self._real, self._imag = real, imag
        return self

    @property
    def real(self):
        return self._real

    @property
    def imag(self):
        return self._imag

    @property
    def conj(self):
        return Cplx(self.real, -self.imag)

    def __pos__(self):
        return self

    def __neg__(self):
        return Cplx(-self.real, -self.imag)

    def __add__(u, v):
        if not isinstance(v, Cplx):
            return Cplx(u.real + v, u.imag + v)
        return Cplx(u.real + v.real, u.imag + v.imag)

    __radd__ = __add__

    def __sub__(u, v):
        if not isinstance(v, Cplx):
            return Cplx(u.real - v, u.imag - v)
        return Cplx(u.real - v.real, u.imag - v.imag)

    __rsub__ = __sub__

    def __mul__(u, v):
        if not isinstance(v, Cplx):
            return Cplx(u.real * v, u.imag * v)
        return Cplx(u.real * v.real - u.imag * v.imag,
                    u.imag * v.real + u.real * v.imag)

    __rmul__ = __mul__

    def __truediv__(u, v):
        if not isinstance(v, Cplx):
            return Cplx(u.real / v, u.imag / v)

        scale = abs(v)
        return (u / scale) * (v.conj / scale)

    def __rtruediv__(u, v):
        return Cplx(v, 0.) / u

    def __abs__(self):
        r"""Compute the complex modulus:
        $$
            \mathbb{C}^{\ldots \times d}
                \to \mathbb{R}_+^{\ldots \times d}
            \colon u + i v \mapsto \lvert u + i v \rvert
            \,. $$
        """
        input = torch.stack([self.real, self.imag], dim=0)
        return torch.norm(input, p=2, dim=0, keepdim=False)

    @property
    def angle(self):
        r"""Compute the complex argument:
        $$
            \mathbb{C}^{\ldots \times d}
                \to \mathbb{R}^{\ldots \times d}
            \colon \underbrace{u + i v}_{r e^{i\phi}} \mapsto \phi
                    = \arctan \tfrac{v}{u}
            \,. $$
        """
        return torch.atan2(self.imag, self.real)

    def apply(self, f, *a, **k):
        r"""Applies the function to real and imaginary parts."""
        return Cplx(f(self.real, *a, **k), f(self.imag, *a, **k))

    def __repr__(self):
        return f"{self.__class__.__name__}(real={self.real}, imag={self.imag})"

    def __bool__(self):
        return self.real is not None or self.imag is not None


def real_to_cplx(input, copy=True):
    """Map real tensor input `... x [D * 2]` to a pair (re, im) with dim `... x D`."""
    *head, n_features = input.shape
    assert (n_features & 1) == 0

    if copy:
        return Cplx(input[..., 0::2].clone(), input[..., 1::2].clone())

    input = input.reshape(*head, -1, 2)
    return Cplx(input[..., 0], input[..., 1])


def cplx_to_real(input, flatten=True):
    """Interleave the complex re-im pair into a real tensor."""
    # re, im = input
    input = torch.stack([input.real, input.imag], dim=-1)
    return input.flatten(-2) if flatten else input


def cplx_exp(input):
    r"""Compute the exponential of the complex tensor in re-im pair."""
    scale = torch.exp(input.real)
    return Cplx(scale * torch.cos(input.imag),
                scale * torch.sin(input.imag))


def cplx_log(input):
    r"""Compute the logarithm of the complex tensor in re-im pair."""
    return Cplx(torch.log(abs(input)), input.angle)


def cplx_sinh(input):
    r"""Compute the hyperbolic sine of the complex tensor in re-im pair."""
    return Cplx(torch.sinh(input.real) * torch.cos(input.imag),
                torch.cosh(input.real) * torch.sin(input.imag))


def cplx_cosh(input):
    r"""Compute the hyperbolic sine of the complex tensor in re-im pair."""
    return Cplx(torch.cosh(input.real) * torch.cos(input.imag),
                torch.sinh(input.real) * torch.sin(input.imag))


def cplx_modrelu(input, threshold=0.5):
    r"""Compute the modulus relu of the complex tensor in re-im pair."""
    # scale = (1 - \trfac{b}{|z|})_+
    modulus = torch.clamp(abs(input), min=1e-5)
    return input * torch.relu(1. - threshold / modulus)


def cplx_phaseshift(input, phi=0.0):
    r"""
    Apply phase shift to the complex tensor in re-im pair.
    $$
        F
        \colon \mathbb{C} \to \mathbb{C}
        \colon z \mapsto z e^{i\phi}
                = u cos \phi - v sin \phi
                    + i (u sin \phi + v cos \phi)
        \,, $$
    with $\phi$ in radians.
    """
    return input * Cplx(torch.cos(phi), torch.sin(phi))


def cplx_linear(input, weight, bias=None):
    r"""Applies a complex linear transformation to the incoming complex
    data: :math:`y = x A^T + b`.
    """
    # W = U + i V,  z = u + i v, c = \Re c + i \Im c
    #  W z + c = (U + i V) (u + i v) + \Re c + i \Im c
    #          = (U u + \Re c - V v) + i (V u + \Im c + U v)
    re = F.linear(input.real, weight.real, None) \
        - F.linear(input.imag, weight.imag, None)
    im = F.linear(input.real, weight.imag, None) \
        + F.linear(input.imag, weight.real, None)

    output = Cplx(re, im)
    if isinstance(bias, Cplx):
        output += bias

    return output


def cplx_conv1d(input, weight, bias=None, stride=1,
                padding=0, dilation=1, groups=1):
    r"""Applies a complex 1d convolution to the incoming complex
    tensor `B x c_in x L`: :math:`y = x \star W + b`.
    """
    # W = U + i V,  z = u + i v, c = \Re c + i \Im c
    bias = bias if isinstance(bias, Cplx) else Cplx(None, None)

    re = F.conv1d(input.real, weight.real, None,
                  stride, padding, dilation, groups) \
        - F.conv1d(input.imag, weight.imag, None,
                   stride, padding, dilation, groups)
    im = F.conv1d(input.real, weight.imag, None,
                  stride, padding, dilation, groups) \
        + F.conv1d(input.imag, weight.real, None,
                   stride, padding, dilation, groups)

    output = Cplx(re, im)
    if isinstance(bias, Cplx):
        output += bias

    return output
