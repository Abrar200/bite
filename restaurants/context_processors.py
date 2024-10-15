from .models import Restaurant
from django.shortcuts import get_object_or_404
from urllib.parse import urlparse, parse_qs
from django.conf import settings

def restaurant_context(request):
    context = {}
    slug = None

    # Try to get the slug from URL kwargs
    if hasattr(request, 'resolver_match') and request.resolver_match:
        slug = request.resolver_match.kwargs.get('slug') or request.resolver_match.kwargs.get('restaurant_slug')

    # If not in kwargs, check GET parameters
    if not slug and 'restaurant_slug' in request.GET:
        slug = request.GET.get('restaurant_slug')

    # If still not found, check the HTTP referer
    if not slug and request.META.get('HTTP_REFERER'):
        referer = urlparse(request.META['HTTP_REFERER'])
        query = parse_qs(referer.query)
        slug = query.get('restaurant_slug', [None])[0]

    # If we have a slug, try to get the restaurant
    if slug:
        try:
            restaurant = Restaurant.objects.get(slug=slug)
            context['restaurant'] = restaurant
            context['restaurant_slug'] = slug
            context['primary_color'] = restaurant.primary_color
            context['logo_image'] = restaurant.logo_image.url if restaurant.logo_image else None
            context['favicon'] = restaurant.favicon.url if restaurant.favicon else None
            context['landing_page_image'] = restaurant.landing_page_image.url if restaurant.landing_page_image else None
            context['landing_page_tagline'] = restaurant.landing_page_tagline
            context['about_us_image1'] = restaurant.about_us_image1.url if restaurant.about_us_image1 else None
            context['about_us_text1'] = restaurant.about_us_text1
            context['about_us_image2'] = restaurant.about_us_image2.url if restaurant.about_us_image2 else None
            context['about_us_text2'] = restaurant.about_us_text2
            context['about_us_image3'] = restaurant.about_us_image3.url if restaurant.about_us_image3 else None
            context['about_us_text3'] = restaurant.about_us_text3
            context['contact_us_image'] = restaurant.contact_us_image.url if restaurant.contact_us_image else None
            context['map_iframe_src'] = restaurant.map_iframe_src
            context['footer_text'] = restaurant.footer_text
            context['facebook_link'] = restaurant.facebook_link
            context['instagram_link'] = restaurant.instagram_link
            context['youtube_link'] = restaurant.youtube_link
            context['twitter_link'] = restaurant.twitter_link
        except Restaurant.DoesNotExist:
            # Log this error or handle it appropriately
            print(f"Restaurant with slug {slug} does not exist")

    return context


def google_maps_api_key(request):
    return {'GOOGLE_MAPS_API_KEY': settings.GOOGLE_MAPS_API_KEY}