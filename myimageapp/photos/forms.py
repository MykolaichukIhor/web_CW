from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Photo


class PhotoForm(forms.ModelForm):
    category_new = forms.CharField(max_length=100, required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('Create new category')}))

    class Meta:
        model = Photo
        fields = ['image', 'description', 'category']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3, 'class': 'form-control', 'placeholder': _('Optional description')}),
            'category': forms.Select(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if self.user:
            self.fields['category'].queryset = self.user.category_set.all()

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.cleaned_data.get('category_new'):
            category, created = self.user.category_set.get_or_create(name=self.cleaned_data['category_new'])
            instance.category = category
        if commit:
            instance.save()
        return instance
