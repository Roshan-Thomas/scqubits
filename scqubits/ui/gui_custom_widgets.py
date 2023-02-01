# gui_custom_widgets.py
#
# This file is part of scqubits: a Python package for superconducting qubits,
# Quantum 5, 583 (2021). https://quantum-journal.org/papers/q-2021-11-17-583/
#
#    Copyright (c) 2019 and later, Jens Koch and Peter Groszkowski
#    All rights reserved.
#
#    This source code is licensed under the BSD-style license found in the
#    LICENSE file in the root directory of this source tree.
############################################################################

from typing import Any, Callable, List, Union

import ipyvuetify
import ipywidgets
import traitlets
from IPython.core.display_functions import display

from scqubits.utils import misc as utils


class ValidatedNumberField(ipyvuetify.TextField):
    _typecheck_func: callable = None
    _type = None
    _current_value = None
    num_value = None

    def __init__(
        self,
        v_model,
        num_type=None,
        v_min=None,
        v_max=None,
        step=None,
        filled=True,
        **kwargs,
    ):
        self.name = kwargs.pop("name", None)
        self._type = num_type if num_type is not None else type(v_model)

        # if "v_model" not in kwargs and "items" in kwargs:
        #     kwargs["v_model"] = kwargs["items"][0]
        self._current_value = v_model

        super().__init__(v_model=v_model, filled=filled, **kwargs)

        if num_type == float:
            TraitletClass = traitlets.Float
            self._typecheck_func = lambda data: utils.is_string_float(data)
            self.step = step if step is not None else 0.1
        elif num_type == int:
            TraitletClass = traitlets.Int
            self._typecheck_func = lambda data: utils.is_string_int(data)
            self.step = step if step is not None else 1
        else:
            raise Exception(f"Not a supported number type: {num_type}")

        self.add_traits(
            num_value=TraitletClass(read_only=True).tag(sync=True),
            v_min=TraitletClass(allow_none=True).tag(sync=True),
            v_max=TraitletClass(allow_none=True).tag(sync=True),
        )
        self.v_min = v_min
        self.v_max = v_max
        self.set_trait("num_value", self._num_value())

        self.observe(self.is_entry_valid, names="v_model")

    def is_entry_valid(self, *args, **kwargs):
        if (
            not self._typecheck_func(self.v_model)
            or (self.v_min not in [None, ""] and self.num_value < self.v_min)
            or (self.v_max not in [None, ""] and self.num_value > self.v_max)
        ):
            self.error = True
            self.rules = ["invalid"]
            return False

        self.rules = [True]
        self.error = False
        self.set_trait("num_value", self._num_value())
        return True

    def _num_value(self):
        if not self.error:
            self._current_value = self._type(self.v_model)
        return self._current_value


class NumberEntryWidget(ValidatedNumberField):
    def __init__(
        self,
        label,
        v_model=None,
        num_type=float,
        step=None,
        v_min=None,
        v_max=None,
        s_min=None,
        s_max=None,
        style_="",
        class_="",
        text_kwargs=None,
        slider_kwargs=None,
    ):
        self.class_ = class_
        self.style_ = style_
        text_kwargs = text_kwargs or {}
        slider_kwargs = slider_kwargs or {}

        super().__init__(
            label=label,
            v_model=v_model,
            num_type=num_type,
            step=step,
            v_min=v_min,
            v_max=v_max,
            **text_kwargs,
        )

        if "style_" not in slider_kwargs:
            slider_kwargs["style_"] = "max-width: 240px; width: 220px;"
        if "class_" not in slider_kwargs:
            slider_kwargs["class_"] = "pt-3"
        self.slider = ipyvuetify.Slider(
            min=s_min, max=s_max, step=step, v_model=v_model, **slider_kwargs
        )

        self._continuous_update_in_progress = False
        self.slider.on_event("start", self.slider_in_progress_toggle)
        self.slider.on_event("end", self.slider_in_progress_toggle)
        self.slider.observe(self.update_textfield, names="v_model")
        self.observe(self.update_slider, names="num_value")

        ipywidgets.jslink((self, "v_max"), (self.slider, "max"))
        ipywidgets.jslink((self, "v_min"), (self.slider, "min"))
        ipywidgets.jslink((self, "disabled"), (self.slider, "disabled"))

    def _ipython_display_(self):
        display(self.widget())

    def widget(self):
        return ipyvuetify.Container(
            class_=self.class_ or "d-flex flex-row pr-4",
            style_=self.style_,
            children=[self, self.slider],
        )

    def update_textfield(self, *args):
        if self._continuous_update_in_progress:
            self.v_model = self.slider.v_model

    def update_slider(self, *args):
        if self.error:
            return
        if self.num_value > self.slider.max:
            self.slider.color = "red"
            self.slider.v_model = self.slider.max
        elif self.num_value < self.slider.min:
            self.slider.color = "red"
            self.slider.v_model = self.slider.min
        else:
            self.slider.color = ""
            self.slider.v_model = self.num_value

    def slider_in_progress_toggle(self, *args):
        self._continuous_update_in_progress = not self._continuous_update_in_progress
        if not self._continuous_update_in_progress:
            self.v_model = str(
                self.slider.v_model
            )  # This is a hack... need to trigger final "change" event


class InitSelect(ipyvuetify.Select):
    def __init__(self, **kwargs):
        if "v_model" not in kwargs and "items" in kwargs:
            kwargs["v_model"] = kwargs["items"][0]
        super().__init__(**kwargs)


class vBtn(ipyvuetify.Btn):
    def __init__(self, **kwargs):
        onclick = kwargs.pop("onclick", None)
        super().__init__(**kwargs)

        if onclick:
            self.on_event("click", onclick)


class DiscreteSetSlider(ipyvuetify.Slider):
    def __init__(self, param_vals, **kwargs):
        self.val_count = len(param_vals)
        self.param_vals = param_vals
        super().__init__(min=0, max=(self.val_count - 1), step=1, v_model=0, **kwargs)

    def current_value(self):
        return self.param_vals[int(self.v_model)]


class IconButton(vBtn):
    def __init__(self, icon_name, **kwargs):
        super().__init__(
            **kwargs,
            min_width=40,
            width=40,
            height=40,
            elevation="0",
            children=[ipyvuetify.Icon(children=[icon_name])],
        )


class NavbarElement(ipyvuetify.ExpansionPanels):
    def __init__(
        self,
        header,
        content: Union[None, ipyvuetify.ExpansionPanelContent] = None,
        children: Union[None, List[ipyvuetify.VuetifyWidget]] = None,
        **kwargs,
    ):
        assert (content and not children) or (children and not content)

        content = (
            content
            if isinstance(content, ipyvuetify.ExpansionPanelContent)
            else ipyvuetify.ExpansionPanelContent(
                class_="text-no-wrap", style_="transform: scale(0.9)", children=children
            )
        )

        super().__init__(
            **kwargs,
            **dict(
                transition=False,
                flat=True,
                v_model=None,
                children=[
                    ipyvuetify.ExpansionPanel(
                        accordion=True,
                        children=[
                            ipyvuetify.ExpansionPanelHeader(
                                disable_icon_rotate=True,
                                style_="font-size: 16px; font-weight: 500",
                                class_="text-no-wrap",
                                children=[header],
                            ),
                            content,
                        ],
                    )
                ],
            ),
        )
