from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.core.files.base import ContentFile
from django.contrib import messages
from django.http import HttpResponse
from django.utils.translation import gettext_lazy as _
# from django.utils.translation import gettext as _
from PIL import Image, ImageFilter, ImageEnhance
import numpy as np
import os
import io
import json
from datetime import datetime

from .forms import PhotoForm
from .models import Category, Photo


# ==============================================================================
# FUNCTION: rgb_to_hsv
# DESCRIPTION:
# Converts an RGB image array to an HSV (Hue, Saturation, Value) image array.
# It uses vectorized NumPy operations instead of standard loops to ensure 
# high performance when processing large image matrices.
# 
# PARAMETERS: 
# - rgb (numpy.ndarray): The input RGB array with values ranging from 0-255.
# 
# RETURNS: 
# - numpy.ndarray: The output HSV array with values ranging from 0.0 to 1.0.
# ==============================================================================
def rgb_to_hsv(rgb):
    rgb = rgb.astype('float')
    hsv = np.zeros_like(rgb)
    
    # Preserve the alpha channel (transparency) if it exists
    hsv[..., 3:] = rgb[..., 3:]
    
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    maxc = np.max(rgb[..., :3], axis=-1)
    minc = np.min(rgb[..., :3], axis=-1)
    
    hsv[..., 2] = maxc / 255.0
    mask = maxc != minc
    hsv[mask, 1] = (maxc - minc)[mask] / maxc[mask]
    
    rc = np.zeros_like(r)
    gc = np.zeros_like(g)
    bc = np.zeros_like(b)
    
    rc[mask] = (maxc - r)[mask] / (maxc - minc)[mask]
    gc[mask] = (maxc - g)[mask] / (maxc - minc)[mask]
    bc[mask] = (maxc - b)[mask] / (maxc - minc)[mask]
    
    hsv[..., 0] = np.select(
        [r == maxc, g == maxc], [bc - gc, 2.0 + rc - bc], default=4.0 + gc - rc)
    hsv[..., 0] = (hsv[..., 0] / 6.0) % 1.0
    return hsv


# ==============================================================================
# FUNCTION: hsv_to_rgb
# DESCRIPTION:
# Converts an HSV array back into an RGB array. Like the conversion to HSV, 
# this function uses vectorized NumPy conditions to map the Hue circle back 
# into standard Red, Green, and Blue channels.
# 
# PARAMETERS: 
# - hsv (numpy.ndarray): The HSV array with values from 0.0 to 1.0.
# 
# RETURNS: 
# - numpy.ndarray: The RGB array with standard integer values (0-255).
# ==============================================================================
def hsv_to_rgb(hsv):
    rgb = np.empty_like(hsv)
    
    # Preserve alpha channel
    rgb[..., 3:] = hsv[..., 3:]
    
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    i = (h * 6.0).astype('uint8')
    f = (h * 6.0) - i
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    i = i % 6
    
    # Select the correct formula based on the hue sector (0-5)
    conditions = [s == 0.0, i == 1, i == 2, i == 3, i == 4, i == 5]
    rgb[..., 0] = np.select(conditions, [v, q, p, p, t, v], default=v) * 255
    rgb[..., 1] = np.select(conditions, [v, v, v, q, p, p], default=t) * 255
    rgb[..., 2] = np.select(conditions, [v, p, t, v, v, q], default=p) * 255
    return rgb.astype('uint8')


# ==============================================================================
# FUNCTION: shift_hue
# DESCRIPTION:
# Shifts the colors of an image along the Hue spectrum.
# 
# PARAMETERS: 
# - arr (numpy.ndarray): RGB image array.
# - hue_shift (float): Value from 0.0 to 1.0 (representing 0 to 360 degrees).
# ==============================================================================
def shift_hue(arr, hue_shift):
    hsv = rgb_to_hsv(arr)
    # Modulo 1.0 ensures the hue value wraps around the color wheel properly
    hsv[..., 0] = (hsv[..., 0] + hue_shift) % 1.0
    return hsv_to_rgb(hsv)


# ==============================================================================
# FUNCTION: adjust_saturation
# DESCRIPTION:
# Multiplies the saturation channel of an image by a given factor.
# 
# PARAMETERS: 
# - arr (numpy.ndarray): RGB image array.
# - sat_factor (float): 0.0 = grayscale, 1.0 = original, >1.0 = increased saturation.
# ==============================================================================
def adjust_saturation(arr, sat_factor):
    hsv = rgb_to_hsv(arr)
    # np.clip ensures the saturation doesn't exceed the absolute limit of 1.0
    hsv[..., 1] = np.clip(hsv[..., 1] * sat_factor, 0.0, 1.0)
    return hsv_to_rgb(hsv)


# ==============================================================================
# FUNCTION: adjust_brightness
# DESCRIPTION:
# Scales the value (brightness) channel of an image in the HSV color space.
# 
# PARAMETERS: 
# - arr (numpy.ndarray): RGB image array.
# - brightness_factor (float): Scaling factor for the brightness.
# ==============================================================================
def adjust_brightness(arr, brightness_factor):
    hsv = rgb_to_hsv(arr)
    hsv[..., 2] = np.clip(hsv[..., 2] * brightness_factor, 0.0, 1.0)
    return hsv_to_rgb(hsv)


# ==============================================================================
# FUNCTION: process_image
# DESCRIPTION:
# The main rendering pipeline. It takes an original image and applies a 
# sequential list of transformations based on user parameters (crop, rotate, 
# brightness, hue, contrast, vignette, etc.). It fluidly switches between 
# NumPy array manipulation and PIL Image methods depending on what is most 
# efficient for a specific filter.
# 
# PARAMETERS: 
# - photo (Photo): The photo model instance containing the file path.
# - params (dict): A dictionary of filter parameters and their float values.
# 
# RETURNS: 
# - PIL.Image: The fully processed image.
# ==============================================================================
def process_image(photo, params):
    img = Image.open(photo.image.path)
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    arr = np.array(img)

    # Crop
    crop_x = float(params.get('crop_x', 0))
    crop_y = float(params.get('crop_y', 0))
    crop_w = float(params.get('crop_w', 100))
    crop_h = float(params.get('crop_h', 100))
    
    # Only crop if dimensions are smaller than 100%
    if crop_w < 100 or crop_h < 100:
        height, width = arr.shape[:2]
        left = int((crop_x / 100) * width)
        top = int((crop_y / 100) * height)
        right = int(left + (crop_w / 100) * width)
        bottom = int(top + (crop_h / 100) * height)
        arr = arr[top:bottom, left:right]

    # Mirror
    if params.get('mirror'):
        arr = np.fliplr(arr)

    # Rotate & Straighten
    rotate = float(params.get('rotate', 0))
    straighten = float(params.get('straighten', 0))
    total_rotate = rotate + straighten
    if total_rotate != 0:
        img = Image.fromarray(arr, 'RGBA')
        img = img.rotate(-total_rotate, expand=True, resample=Image.BICUBIC)
        arr = np.array(img)

    # Scale
    scale = int(params.get('scale', 100))
    if scale != 100:
        img = Image.fromarray(arr, 'RGBA')
        new_size = (int(img.width * scale / 100), int(img.height * scale / 100))
        img = img.resize(new_size, Image.LANCZOS)
        arr = np.array(img)

    # Hue
    hue = float(params.get('hue', 0))
    if hue != 0:
        hue_shift = hue / 360.0
        arr = shift_hue(arr, hue_shift)

    # Temperature
    # Simulated by slightly shifting the hue towards orange/blue and adjusting saturation
    temperature = float(params.get('temperature', 0))
    if temperature != 0:
        temp_hue_shift = -temperature * 0.0008
        arr = shift_hue(arr, temp_hue_shift)
        if abs(temperature) > 20:
            sat_adj = 1 + (abs(temperature) / 500)
            arr = adjust_saturation(arr, sat_adj)

    # Tint
    tint = float(params.get('tint', 0))
    if tint != 0:
        tint_hue_shift = tint * 0.003
        arr = shift_hue(arr, tint_hue_shift)

    # Saturation + Vibrance
    saturation = float(params.get('saturation', 0))
    vibrance = float(params.get('vibrance', 0))
    if saturation != 0 or vibrance != 0:
        sat_factor = 1 + (saturation / 100) + (vibrance / 200)
        sat_factor = max(0, sat_factor)
        arr = adjust_saturation(arr, sat_factor)

    # Brightness + Exposure
    brightness = float(params.get('brightness', 0))
    exposure = float(params.get('exposure', 0))
    if brightness != 0 or exposure != 0:
        bright_factor = 1 + (brightness / 100) + (exposure / 100)
        bright_factor = max(0, bright_factor)
        arr = adjust_brightness(arr, bright_factor)

    # Contrast
    contrast = float(params.get('contrast', 0))
    if contrast != 0:
        img = Image.fromarray(arr, 'RGBA').convert('RGB')
        contrast_factor = 1 + (contrast / 100)
        img = ImageEnhance.Contrast(img).enhance(contrast_factor)
        arr = np.array(img.convert('RGBA'))

    # Sharpness
    sharpness = float(params.get('sharpness', 0))
    if sharpness != 0:
        img = Image.fromarray(arr, 'RGBA').convert('RGB')
        if sharpness > 0:
            img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=int(sharpness), threshold=0))
        else:
            img = img.filter(ImageFilter.GaussianBlur(radius=abs(sharpness) / 33))
        arr = np.array(img.convert('RGBA'))

    # Blur
    blur = float(params.get('blur', 0))
    if blur > 0:
        img = Image.fromarray(arr, 'RGBA').convert('RGB')
        img = img.filter(ImageFilter.GaussianBlur(radius=blur))
        arr = np.array(img.convert('RGBA'))

    # Vignette
    vignette = float(params.get('vignette', 0))
    if vignette != 0:
        height, width = arr.shape[:2]
        
        # Create a grid representing coordinate distances from the center
        y, x = np.ogrid[:height, :width]
        cx, cy = width / 2, height / 2
        dist = np.sqrt((x - cx)**2 + (y - cy)**2)
        max_dist = np.sqrt(cx**2 + cy**2)
        
        if vignette > 0:
            # Darken edges
            mask = np.clip((dist / max_dist) * (vignette / 100), 0, 1)
            mask = mask[:, :, np.newaxis]
            arr[:, :, :3] = (arr[:, :, :3] * (1 - mask * 0.7)).astype('uint8')
        else:
            # Lighten edges (white vignette)
            mask = np.clip((1 - dist / max_dist) * (abs(vignette) / 100), 0, 1)
            mask = mask[:, :, np.newaxis]
            arr[:, :, :3] = np.clip(arr[:, :, :3] + (255 - arr[:, :, :3]) * mask * 0.7, 0, 255).astype('uint8')

    # Highlights
    highlights = float(params.get('highlights', 0))
    if highlights != 0:
        gray = np.mean(arr[:, :, :3], axis=2)
        highlight_mask = gray > 128
        factor = 1 + (highlights / 100) * (gray - 128) / 127
        factor = factor[:, :, np.newaxis]
        arr[:, :, :3] = np.where(
            highlight_mask[:, :, np.newaxis],
            np.clip(arr[:, :, :3] * factor, 0, 255),
            arr[:, :, :3]
        ).astype('uint8')

    # Shadows
    shadows = float(params.get('shadows', 0))
    if shadows != 0:
        gray = np.mean(arr[:, :, :3], axis=2)
        shadow_mask = gray < 128
        factor = 1 + (shadows / 100) * (128 - gray) / 128
        factor = np.clip(factor, 0, 3)[:, :, np.newaxis]
        arr[:, :, :3] = np.where(
            shadow_mask[:, :, np.newaxis],
            np.clip(arr[:, :, :3] * factor, 0, 255),
            arr[:, :, :3]
        ).astype('uint8')

    # Clarity
    clarity = float(params.get('clarity', 0))
    if clarity != 0:
        gray = np.mean(arr[:, :, :3], axis=2)
        midtone_mask = (gray >= 64) & (gray <= 192)
        factor = 1 + (clarity / 100)
        arr[:, :, :3] = np.where(
            midtone_mask[:, :, np.newaxis],
            np.clip(128 + (arr[:, :, :3] - 128) * factor, 0, 255),
            arr[:, :, :3]
        ).astype('uint8')

    # Noise
    noise = float(params.get('noise', 0))
    if noise > 0:
        img = Image.fromarray(arr, 'RGBA').convert('RGB')
        img = img.filter(ImageFilter.GaussianBlur(radius=noise / 25))
        arr = np.array(img.convert('RGBA'))

    # Texture
    texture = float(params.get('texture', 0))
    if texture != 0:
        img = Image.fromarray(arr, 'RGBA').convert('RGB')
        if texture > 0:
            edges = img.filter(ImageFilter.FIND_EDGES).convert('RGB')
            img = Image.blend(img, edges, texture / 200)
        else:
            img = img.filter(ImageFilter.SMOOTH_MORE)
        arr = np.array(img.convert('RGBA'))

    return Image.fromarray(arr, 'RGBA')


# ==============================================================================
# FUNCTION: signup
# DESCRIPTION:
# Handles new user registration. If the request is POST, it attempts to save 
# the new user. Otherwise, it renders an empty UserCreationForm.
# ==============================================================================
def signup(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('photos_login')
    else:
        form = UserCreationForm()

    return render(request, 'photos/signup.html', {'form': form})


# ==============================================================================
# FUNCTION: detect_mobile_device
# DESCRIPTION:
# Analyzes the HTTP 'User-Agent' string to heuristically determine if the 
# request is coming from a mobile phone, tablet, or desktop.
# 
# RETURNS: 
# - dict: Boolean flags for 'is_mobile', 'is_tablet', and 'is_desktop'.
# ==============================================================================
def detect_mobile_device(request):
    user_agent = request.META.get('HTTP_USER_AGENT', '').lower()
    
    mobile_keywords = [
        'mobile', 'android', 'iphone', 'ipad', 'ipod', 
        'blackberry', 'windows phone', 'opera mini', 'iemobile',
        'phone', 'tablet', 'kindle', 'silk'
    ]
    
    is_mobile = any(keyword in user_agent for keyword in mobile_keywords)
    is_tablet = 'tablet' in user_agent or 'ipad' in user_agent
    is_desktop = not is_mobile and not is_tablet
    
    return {
        'is_mobile': is_mobile,
        'is_tablet': is_tablet,
        'is_desktop': is_desktop
    }


# ==============================================================================
# FUNCTION: gallery
# DESCRIPTION:
# The primary view for rendering the photo gallery. It handles extensive 
# filtering logic (by category, search queries, and various date ranges). 
# It also delegates rendering to mobile or desktop templates based on device 
# detection or explicit URL parameters.
# ==============================================================================
@login_required
@never_cache
def gallery(request):
    category = request.GET.get('category')
    search_query = request.GET.get('search', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    date_after = request.GET.get('date_after', '')
    date_before = request.GET.get('date_before', '')
    
    force_mobile = request.GET.get('mobile') == '1'
    force_desktop = request.GET.get('desktop') == '1'
    
    device_info = detect_mobile_device(request)
    
    if force_mobile:
        template_name = 'photos/gallery_mobile.html'
        is_mobile_version = True
    elif force_desktop:
        template_name = 'photos/gallery.html'
        is_mobile_version = False
    elif device_info['is_mobile'] or device_info['is_tablet']:
        template_name = 'photos/gallery_mobile.html'
        is_mobile_version = True
    else:
        template_name = 'photos/gallery.html'
        is_mobile_version = False
    
    photos = Photo.objects.filter(user=request.user).order_by('-created_at')
    
    if category:
        photos = photos.filter(category__name__icontains=category)
    
    if search_query:
        photos = photos.filter(description__icontains=search_query)
    
    if date_after:
        try:
            date_after_obj = datetime.strptime(date_after, '%Y-%m-%d').date()
            photos = photos.filter(created_at__date__gte=date_after_obj)
        except ValueError:
            pass
    
    if date_before:
        try:
            date_before_obj = datetime.strptime(date_before, '%Y-%m-%d').date()
            photos = photos.filter(created_at__date__lte=date_before_obj)
        except ValueError:
            pass
    
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
            photos = photos.filter(created_at__date__gte=date_from_obj)
        except ValueError:
            pass
    
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
            photos = photos.filter(created_at__date__lte=date_to_obj)
        except ValueError:
            pass
    
    categories = request.user.category_set.all()
    single_date = date_after or date_before
    
    # Pre-render a JSON array for the mobile view frontend to allow instant 
    # DOM updates without additional requests.
    if is_mobile_version:
        photos_json = [
            {
                'id': p.id,
                'url': p.image.url,
                'description': p.description or '',
                'category_name': p.category.name if p.category else 'None',
                'created_at': p.created_at.strftime("%Y-%m-%d"),
                'created_at_full': p.created_at.strftime("%d.%m.%Y %H:%M")
            }
            for p in photos
        ]
        
        context = {
            'categories': categories,
            'photos': photos,
            'photos_json': json.dumps(photos_json),
            'device_type': 'mobile' if device_info['is_mobile'] else 'tablet',
            'photo_count': photos.count(),
            'search_query': search_query,
            'date_from': date_from,
            'date_to': date_to,
            'date_after': date_after,
            'date_before': date_before,
            'single_date': single_date,
            'category': category,
        }
    else:
        context = {
            'categories': categories,
            'photos': photos,
            'search_query': search_query,
            'date_from': date_from,
            'date_to': date_to,
            'date_after': date_after,
            'date_before': date_before,
            'single_date': single_date,
            'category': category,
        }
    
    return render(request, template_name, context)


# ==============================================================================
# FUNCTION: viewPhoto
# DESCRIPTION:
# Renders the single-photo viewing page. It calculates the current photo's 
# index within the user's entire collection to provide 'Next' and 'Previous' 
# navigation IDs.
# ==============================================================================
@login_required
@never_cache
def viewPhoto(request, pk):
    photo = get_object_or_404(Photo, id=pk, user=request.user)
    
    device_info = detect_mobile_device(request)
    force_mobile = request.GET.get('mobile') == '1'
    force_desktop = request.GET.get('desktop') == '1'
    
    if force_mobile:
        template_name = 'photos/photo_mobile.html'
    elif force_desktop:
        template_name = 'photos/photo.html'
    elif device_info['is_mobile'] or device_info['is_tablet']:
        template_name = 'photos/photo_mobile.html'
    else:
        template_name = 'photos/photo.html'
    
    all_photos = Photo.objects.filter(user=request.user).order_by('-created_at')
    
    current_index = -1
    gallery_photos = []
    
    # Identify index for navigation buttons
    for idx, p in enumerate(all_photos):
        gallery_photos.append({
            'id': p.id,
            'url': p.image.url,
            'description': p.description or '',
            'category_name': p.category.name if p.category else 'None'
        })
        if p.id == photo.id:
            current_index = idx
    
    has_prev = current_index > 0
    has_next = current_index < len(all_photos) - 1
    prev_id = all_photos[current_index - 1].id if has_prev else None
    next_id = all_photos[current_index + 1].id if has_next else None
    
    context = {
        'photo': photo,
        'gallery_photos': json.dumps(gallery_photos),
        'has_prev': has_prev,
        'has_next': has_next,
        'prev_id': prev_id,
        'next_id': next_id,
        'current_index': current_index + 1,
        'total_photos': len(all_photos),
    }
    
    return render(request, template_name, context)


# ==============================================================================
# FUNCTION: uploadPhoto
# DESCRIPTION:
# Processes the photo upload form. Ensures that the currently logged-in user 
# is assigned as the owner of the uploaded file.
# ==============================================================================
@login_required
@never_cache
def uploadPhoto(request):
    device_info = detect_mobile_device(request)
    force_mobile = request.GET.get('mobile') == '1'
    force_desktop = request.GET.get('desktop') == '1'
    
    if force_mobile:
        template_name = 'photos/upload_mobile.html'
    elif force_desktop:
        template_name = 'photos/upload.html'
    elif device_info['is_mobile'] or device_info['is_tablet']:
        template_name = 'photos/upload_mobile.html'
    else:
        template_name = 'photos/upload.html'
    
    if request.method == 'POST':
        form = PhotoForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            photo = form.save(commit=False)
            photo.user = request.user
            photo.save()
            messages.success(request, _('Photo uploaded successfully!'))
            return redirect('gallery')
    else:
        form = PhotoForm(user=request.user)
    
    context = {
        'form': form,
    }
    return render(request, template_name, context)


# ==============================================================================
# FUNCTION: editPhoto
# DESCRIPTION:
# Handles the server-side logic for saving an edited photo. 
# It intercepts the filter parameters, applies them via `process_image`, 
# and then executes logic to either overwrite the current file or save it 
# as an entirely new database record ("Save As").
# ==============================================================================
@login_required
@never_cache
def editPhoto(request, pk):
    photo = get_object_or_404(Photo, id=pk, user=request.user)
    
    device_info = detect_mobile_device(request)
    force_mobile = request.GET.get('mobile') == '1'
    force_desktop = request.GET.get('desktop') == '1'
    
    if force_mobile:
        template_name = 'photos/edit_mobile.html'
    elif force_desktop:
        template_name = 'photos/edit.html'
    elif device_info['is_mobile'] or device_info['is_tablet']:
        template_name = 'photos/edit_mobile.html'
    else:
        template_name = 'photos/edit.html'
    
    if request.method == 'POST':
        save_as = request.POST.get('save_as') == '1'
        new_filename = request.POST.get('new_filename') if save_as else None

        params = {k: v for k, v in request.POST.items()}
        img = process_image(photo, params)

        if save_as:
            description = request.POST.get('description', '')
            category_id = request.POST.get('category')
            category_new = request.POST.get('category_new', '')
            
            if new_filename:
                base, ext = os.path.splitext(new_filename)
                description = base
            
            new_photo = Photo(user=request.user, description=description)
            
            if category_new:
                category, created = Category.objects.get_or_create(name=category_new, user=request.user)
                new_photo.category = category
            elif category_id:
                try:
                    category = Category.objects.get(id=category_id, user=request.user)
                    new_photo.category = category
                except Category.DoesNotExist:
                    pass
            
            if new_filename:
                base, ext = os.path.splitext(new_filename)
                if not ext:
                    ext = '.jpg'
                filename_to_save = base + ext
            else:
                original_name = photo.image.name.split("/")[-1]
                base, ext = os.path.splitext(original_name)
                filename_to_save = f'{base}_edited{ext}'
            
            # Save the processed PIL Image to an in-memory buffer to pass to Django
            buffer = io.BytesIO()
            img_format = img.format if hasattr(img, 'format') and img.format else 'JPEG'
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            img.save(buffer, format=img_format)
            buffer.seek(0)
            
            new_photo.image.save(
                filename_to_save, 
                ContentFile(buffer.getvalue()),
                save=False
            )
            new_photo.save()
            
            messages.success(request, _('New photo saved as: {}').format(new_photo.image.name))
            
        else:
            form = PhotoForm(request.POST, user=request.user, instance=photo)
            if form.is_valid():
                updated_photo = form.save(commit=False)
                
                old_image_path = photo.image.path if photo.image else None
                old_image_name = photo.image.name if photo.image else None
                
                buffer = io.BytesIO()
                img_format = img.format if hasattr(img, 'format') and img.format else 'JPEG'
                if img.mode in ('RGBA', 'P'):
                    img = img.convert('RGB')
                img.save(buffer, format=img_format)
                buffer.seek(0)
                
                # Delete old file before saving the new one to prevent orphaned files
                if old_image_path and os.path.exists(old_image_path):
                    os.remove(old_image_path)
                
                filename = os.path.basename(old_image_name)
                updated_photo.image.save(
                    filename,
                    ContentFile(buffer.getvalue()),
                    save=False
                )
                updated_photo.save()
                
                messages.success(request, _('Photo updated successfully!'))
            else:
                context = {
                    'form': form, 
                    'photo': photo,
                }
                return render(request, template_name, context)
        
        return redirect('gallery')
    else:
        form = PhotoForm(user=request.user, instance=photo)
    
    context = {
        'form': form, 
        'photo': photo,
    }
    return render(request, template_name, context)


# ==============================================================================
# FUNCTION: previewPhoto
# DESCRIPTION:
# Acts as a real-time API endpoint for the image editor. It receives a set 
# of URL query parameters (GET request), applies all filters via `process_image`, 
# and returns the raw JPEG binary data directly in the HTTP response.
# Includes diagnostic print statements to log applied filters to the console.
# ==============================================================================
@login_required
@never_cache
def previewPhoto(request, pk):
    photo = get_object_or_404(Photo, id=pk, user=request.user)
    params = {k: v for k, v in request.GET.items()}
    
    print("\n" + "="*60)
    print(f"PREVIEW REQUEST FOR PHOTO ID: {pk}")
    print("="*60)
    print(f"User: {request.user.username}")
    print(f"Photo: {photo.image.name}")
    print("\nALL PARAMETERS RECEIVED:")
    print("-"*60)
    
    core_params = ['brightness', 'contrast', 'exposure', 'highlights', 'shadows']
    color_params = ['saturation', 'vibrance', 'temperature', 'tint', 'hue']
    detail_params = ['sharpness', 'clarity', 'noise', 'texture']
    geometry_params = ['rotate', 'straighten', 'scale', 'mirror', 'crop_x', 'crop_y', 'crop_w', 'crop_h']
    effect_params = ['blur', 'vignette']
    
    print("\nCORE ADJUSTMENTS:")
    for param in core_params:
        val = params.get(param, '0')
        print(f"  {param:15} = {val}")
    
    print("\nCOLOR CONTROLS:")
    for param in color_params:
        val = params.get(param, '0')
        print(f"  {param:15} = {val}")
    
    print("\nDETAIL & SHARPNESS:")
    for param in detail_params:
        val = params.get(param, '0')
        print(f"  {param:15} = {val}")
    
    print("\nGEOMETRY & FRAMING:")
    for param in geometry_params:
        val = params.get(param, '0' if param not in ['mirror'] else '')
        print(f"  {param:15} = {val}")
    
    print("\nEFFECTS:")
    for param in effect_params:
        val = params.get(param, '0')
        print(f"  {param:15} = {val}")
    
    print("="*60 + "\n")
    
    img = process_image(photo, params)
    
    buffer = io.BytesIO()
    if img.mode in ('RGBA', 'P'):
        img = img.convert('RGB')
    
    # Save optimized JPEG to memory and return as direct image response
    img.save(buffer, format='JPEG', quality=85)
    buffer.seek(0)
    
    return HttpResponse(buffer.getvalue(), content_type='image/jpeg')


# ==============================================================================
# FUNCTION: deletePhoto
# DESCRIPTION:
# Confirms and processes the deletion of a photo record. If confirmed via POST, 
# it securely removes the associated physical file from the file system before 
# deleting the database entry.
# ==============================================================================
@login_required
def deletePhoto(request, pk):
    photo = get_object_or_404(Photo, id=pk, user=request.user)
    
    device_info = detect_mobile_device(request)
    force_mobile = request.GET.get('mobile') == '1'
    force_desktop = request.GET.get('desktop') == '1'
    
    if force_mobile:
        template_name = 'photos/delete_mobile.html'
    elif force_desktop:
        template_name = 'photos/delete.html'
    elif device_info['is_mobile'] or device_info['is_tablet']:
        template_name = 'photos/delete_mobile.html'
    else:
        template_name = 'photos/delete.html'
    
    if request.method == 'POST':
        # Remove file from disk
        if photo.image and os.path.exists(photo.image.path):
            os.remove(photo.image.path)
        photo.delete()
        messages.success(request, _('Photo "{}" deleted successfully!').format(photo.description))
        return redirect('gallery')
    
    context = {
        'photo': photo,
    }
    return render(request, template_name, context)