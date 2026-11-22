"""Small nested serializers reused across apps (kept here to avoid circular imports)."""
from rest_framework import serializers


class PlantMiniSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    common_name = serializers.CharField()


class PlantMiniStatusSerializer(PlantMiniSerializer):
    status = serializers.CharField()


class ContributorSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    display_name = serializers.CharField(source="public_name")


class ContributorRepSerializer(ContributorSerializer):
    reputation = serializers.IntegerField()


class ReviewMiniSerializer(serializers.Serializer):
    decision = serializers.CharField()
    comment = serializers.CharField()
    created_at = serializers.DateTimeField()


def paginate_nested(request, queryset, serializer_class, context):
    """Paginated block inside a bigger response, e.g. the gallery inside plant details."""
    from rest_framework.pagination import PageNumberPagination

    paginator = PageNumberPagination()
    page = paginator.paginate_queryset(queryset, request)
    data = serializer_class(page, many=True, context=context).data
    return {
        "count": paginator.page.paginator.count,
        "next": paginator.get_next_link(),
        "previous": paginator.get_previous_link(),
        "results": data,
    }
