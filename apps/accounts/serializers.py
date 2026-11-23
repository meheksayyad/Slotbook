from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import User


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8, style={"input_type": "password"})

    class Meta:
        model = User
        fields = ["id", "email", "password", "first_name", "last_name", "phone"]
        read_only_fields = ["id"]

    def validate_email(self, value):
        value = value.lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def validate(self, attrs):
        validate_password(attrs["password"], User(email=attrs["email"]))
        return attrs

    def create(self, validated):
        # Public registration always creates customers; owners are provisioned by admins.
        return User.objects.create_user(role=User.Role.CUSTOMER, **validated)


class MeSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name", "phone", "role"]
        read_only_fields = ["id", "email", "role"]
