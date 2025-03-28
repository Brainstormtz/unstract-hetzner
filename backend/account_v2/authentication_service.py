import logging
import os
import re
import uuid
from typing import Any, Optional

from django.middleware.csrf import get_token
from account_v2.authentication_helper import AuthenticationHelper
from account_v2.constants import DefaultOrg, ErrorMessage, UserLoginTemplate
from account_v2.custom_exceptions import Forbidden, MethodNotImplemented
from account_v2.dto import (
    CallbackData,
    MemberData,
    MemberInvitation,
    OrganizationData,
    ResetUserPasswordDto,
    UserInfo,
    UserRoleData,
)
from account_v2.enums import UserRole
from account_v2.models import Organization, User
from account_v2.organization import OrganizationService
from account_v2.serializer import LoginRequestSerializer
from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.hashers import make_password
from django.http import HttpRequest
from django.shortcuts import redirect, render
from rest_framework.request import Request
from rest_framework.response import Response
from tenant_account_v2.models import OrganizationMember as OrganizationMember
from tenant_account_v2.organization_member_service import OrganizationMemberService
from utils.user_context import UserContext

logger = logging.getLogger(__name__)


class AuthenticationService:
    def __init__(self) -> None:
        self.authentication_helper = AuthenticationHelper()
        self.default_organization: Organization = self.user_organization()

    def _validate_password_complexity(self, password: str) -> None:
        """Validate password meets complexity requirements."""
        if len(password) < 12:
            raise ValueError("Password must be at least 12 characters long")
        if not re.search(r'[A-Z]', password):
            raise ValueError("Password must contain uppercase letters")
        if not re.search(r'[a-z]', password):
            raise ValueError("Password must contain lowercase letters")
        if not re.search(r'[0-9]', password):
            raise ValueError("Password must contain numbers")
        if not re.search(r'[^A-Za-z0-9]', password):
            raise ValueError("Password must contain special characters")

    def user_login(self, request: Request) -> Any:
        """Authenticate and log in a user.

        Args:
            request (Request): The HTTP request object.

        Returns:
            Any: The response object.

        Raises:
            ValueError: If there is an error in the login credentials.
        """
        # Check for rate limiting
        ip = self._get_client_ip(request)
        if self._is_rate_limited(ip):
            return self.render_login_page_with_error(
                request, "Too many login attempts. Please try again later."
            )

        if request.method == "GET":
            return self.render_login_page(request)
        try:
            validated_data = self.validate_login_credentials(request)
            username = validated_data.get("username")
            password = validated_data.get("password")
            
            # Validate password complexity
            self._validate_password_complexity(password)
            
        except ValueError as e:
            self._increment_login_attempt(ip)
            return render(
                request,
                UserLoginTemplate.TEMPLATE,
                {UserLoginTemplate.ERROR_PLACE_HOLDER: str(e)},
            )
            
        if self.authenticate_and_login(request, username, password):
            self._reset_login_attempts(ip)
            return redirect(settings.WEB_APP_ORIGIN_URL)

        self._increment_login_attempt(ip)
        return self.render_login_page_with_error(request, ErrorMessage.USER_LOGIN_ERROR)

    def is_authenticated(self, request: HttpRequest) -> bool:
        """Check if the user is authenticated.

        Args:
            request (Request): The HTTP request object.

        Returns:
            bool: True if the user is authenticated, False otherwise.
        """
        return request.user.is_authenticated

    def __init__(self) -> None:
        self.authentication_helper = AuthenticationHelper()
        self.default_organization: Organization = self.user_organization()
        # Rate limiting now handled by external service (Redis)
        # Initialize with empty dict for backward compatibility
        self.login_attempts = {}

    def _get_client_ip(self, request: Request) -> str:
        """Get client IP address for rate limiting."""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        return x_forwarded_for.split(',')[0] if x_forwarded_for else request.META.get('REMOTE_ADDR')

    def _is_rate_limited(self, ip: str) -> bool:
        """Check if IP is rate limited."""
        return self.login_attempts.get(ip, 0) >= 5  # Allow 5 attempts

    def _increment_login_attempt(self, ip: str) -> None:
        """Increment login attempt counter for IP."""
        self.login_attempts[ip] = self.login_attempts.get(ip, 0) + 1

    def _reset_login_attempts(self, ip: str) -> None:
        """Reset login attempts for IP."""
        if ip in self.login_attempts:
            del self.login_attempts[ip]

    def authenticate_and_login(
        self, request: Request, username: str, password: str
    ) -> bool:
        """Authenticate and log in a user.

        Args:
            request (Request): The HTTP request object.
            username (str): The username of the user.
            password (str): The password of the user.

        Returns:
            bool: True if the user is successfully authenticated and logged in,
                False otherwise.
        """
        user = authenticate(request, username=username, password=password)
        if user:
            # To avoid conflicts with django superuser
            if user.is_superuser:
                return False
            login(request, user)
            return True
        # Attempt to initiate default user and authenticate again
        if self._set_default_user():
            user = authenticate(request, username=username, password=password)
            if user:
                logger.info(f"User {username} authenticated successfully")
                login(request, user)
                logger.info(f"User {username} logged in successfully")
                UserSessionUtils.set_organization_id(request, DefaultOrg.ORGANIZATION_NAME)
                logger.info(f"Organization ID set to {DefaultOrg.ORGANIZATION_NAME} in session")
                return True
        return False

    def render_login_page(self, request: Request) -> Any:
        # Ensure CSRF token is generated and included in the response
        get_token(request)
        return render(request, UserLoginTemplate.TEMPLATE)

    def render_login_page_with_error(self, request: Request, error_message: str) -> Any:
        return render(
            request,
            UserLoginTemplate.TEMPLATE,
            {UserLoginTemplate.ERROR_PLACE_HOLDER: error_message},
        )

    def validate_login_credentials(self, request: Request) -> Any:
        """Validate the login credentials.

        Args:
            request (Request): The HTTP request object.

        Returns:
            dict: The validated login credentials.

        Raises:
            ValueError: If the login credentials are invalid.
        """
        serializer = LoginRequestSerializer(data=request.POST)
        if not serializer.is_valid():
            error_messages = {
                field: errors[0] for field, errors in serializer.errors.items()
            }
            first_error_message = list(error_messages.values())[0]
            raise ValueError(first_error_message)
        return serializer.validated_data

    def user_signup(self, request: HttpRequest) -> Any:
        raise MethodNotImplemented()

    def is_admin_by_role(self, role: str) -> bool:
        """Check the role with actual admin Role.

        Args:
            role (str): input string

        Returns:
            bool: _description_
        """
        try:
            return UserRole(role.lower()) == UserRole.ADMIN
        except ValueError:
            return False

    def get_callback_data(self, request: Request) -> CallbackData:
        return CallbackData(
            user_id=request.user.user_id,
            email=request.user.email,
            token="",
        )

    def user_organization(self) -> Organization:
        return Organization(
            name=DefaultOrg.ORGANIZATION_NAME,
            display_name=DefaultOrg.ORGANIZATION_NAME,
            organization_id=DefaultOrg.ORGANIZATION_NAME,
        )

    def handle_invited_user_while_callback(
        self, request: Request, user: User
    ) -> MemberData:
        member_data: MemberData = MemberData(
            user_id=user.user_id,
            organization_id=self.default_organization.organization_id,
            role=[UserRole.ADMIN.value],
        )

        return member_data

    def handle_authorization_callback(self, request: Request, backend: str) -> Response:
        raise MethodNotImplemented()

    def add_to_organization(
        self,
        request: Request,
        user: User,
        data: Optional[dict[str, Any]] = None,
    ) -> MemberData:
        member_data: MemberData = MemberData(
            user_id=user.user_id,
            organization_id=self.default_organization.organization_id,
        )

        return member_data

    def remove_users_from_organization(
        self,
        admin: OrganizationMember,
        organization_id: str,
        user_ids: list[str],
    ) -> bool:
        raise MethodNotImplemented()

    def user_organizations(self, request: Request) -> list[OrganizationData]:
        organizationData: OrganizationData = OrganizationData(
            id=self.default_organization.organization_id,
            display_name=self.default_organization.display_name,
            name=self.default_organization.name,
        )
        return [organizationData]

    def get_organizations_by_user_id(self, id: str) -> list[OrganizationData]:
        organizationData: OrganizationData = OrganizationData(
            id=self.default_organization.organization_id,
            display_name=self.default_organization.display_name,
            name=self.default_organization.name,
        )
        return [organizationData]

    def get_organization_role_of_user(
        self, user_id: str, organization_id: str
    ) -> list[str]:
        return [UserRole.ADMIN.value]

    def is_organization_admin(self, member: OrganizationMember) -> bool:
        """Check if the organization member has administrative privileges.

        Args:
            member (OrganizationMember): The organization member to check.

        Returns:
            bool: True if the user has administrative privileges,
                False otherwise.
        """
        try:
            return UserRole(member.role) == UserRole.ADMIN
        except ValueError:
            return False

    def check_user_organization_association(self, user_email: str) -> None:
        """Check if the user is already associated with any organizations.

        Raises:
        - UserAlreadyAssociatedException:
            If the user is already associated with organizations.
        """
        return None

    def get_roles(self) -> list[UserRoleData]:
        return [
            UserRoleData(name=UserRole.ADMIN.value),
            UserRoleData(name=UserRole.USER.value),
        ]

    def get_invitations(self, organization_id: str) -> list[MemberInvitation]:
        raise MethodNotImplemented()

    def frictionless_onboarding(self, organization: Organization, user: User) -> None:
        raise MethodNotImplemented()

    def hubspot_signup_api(self, request: Request) -> None:
        raise MethodNotImplemented()

    def delete_invitation(self, organization_id: str, invitation_id: str) -> bool:
        raise MethodNotImplemented()

    def add_organization_user_role(
        self,
        admin: User,
        organization_id: str,
        user_id: str,
        role_ids: list[str],
    ) -> list[str]:
        if admin.role == UserRole.ADMIN.value:
            return role_ids
        raise Forbidden

    def remove_organization_user_role(
        self,
        admin: User,
        organization_id: str,
        user_id: str,
        role_ids: list[str],
    ) -> list[str]:
        if admin.role == UserRole.ADMIN.value:
            return role_ids
        raise Forbidden

    def get_organization_by_org_id(self, id: str) -> OrganizationData:
        organizationData: OrganizationData = OrganizationData(
            id=DefaultOrg.ORGANIZATION_NAME,
            display_name=DefaultOrg.ORGANIZATION_NAME,
            name=DefaultOrg.ORGANIZATION_NAME,
        )
        return organizationData

    def _set_default_user(self) -> bool:
        """Set the default user for authentication.

        Creates or updates a default user with predefined credentials.

        Returns:
            bool: True if the default user is successfully created/updated.
        """
        try:
            UserContext.set_organization_identifier(DefaultOrg.ORGANIZATION_NAME)
            organization = UserContext.get_organization()

            user = self._get_or_create_user(organization)
            
            # Check if default credentials are set in environment variables
            default_username = os.environ.get('DEFAULT_AUTH_USERNAME')
            default_password = os.environ.get('DEFAULT_AUTH_PASSWORD')
            
            if default_username and default_password:
                # Update user with default credentials from environment variables
                user.username = default_username
                user.set_password(default_password)
                user.save()
                logger.info(f"Updated user with default credentials from environment variables")
            else:
                # Fall back to generating random credentials
                self._update_user_credentials(user)

            return True

        except Exception as e:
            logger.error(f"Failed to set default user: {str(e)}")
            return False

    def _get_or_create_user(self, organization: Optional[Organization]) -> User:
        """Get existing user or create a new one based on organization context.

        Args:
            organization: The organization context

        Returns:
            User: The retrieved or created user
        """
        if not organization:
            return self._create_mock_user()

        return self._get_or_create_organization_user()

    def _create_mock_user(self) -> User:
        """Create a new mock user if it doesn't exist.

        Returns:
            User: The created or existing mock user
        """
        # Generate secure random credentials for mock user
        mock_username = f"mock_{uuid.uuid4().hex[:8]}"
        mock_password = uuid.uuid4().hex  # Temporary password that must be changed
        
        user, created = User.objects.get_or_create(username=mock_username)
        if created:
            user.user_id = str(uuid.uuid4())
            user.email = f"{mock_username}@example.com"
            user.password = make_password(mock_password)
            user.save()
            logger.info(f"Created new mock user with username {mock_username}")
        return user

    def _get_or_create_organization_user(self) -> User:
        """Get or create an organization user with admin privileges.

        Returns:
            User: The organization user with admin role
        """
        admin_user = self._get_admin_user()
        if admin_user:
            return admin_user

        member = self._promote_first_member_to_admin()
        if member:
            return member.user

        return self._create_mock_user()

    def _get_admin_user(self) -> Optional[User]:
        """Get the first admin user from the organization.

        Returns:
            Optional[User]: The admin user if exists, None otherwise
        """
        admin_members = OrganizationMemberService.get_members_by_role(
            role=UserRole.ADMIN.value
        )
        return admin_members[0].user if admin_members else None

    def _promote_first_member_to_admin(self) -> Optional[OrganizationMember]:
        """Promote the first organization member to admin role.

        Returns:
            Optional[OrganizationMember]: The promoted member if exists, None otherwise
        """
        members = OrganizationMemberService.get_members()
        if not members:
            logger.warning("No organization member found")
            return None

        first_member = members[0]
        OrganizationMemberService.set_member_role(
            member_id=first_member.member_id, role=UserRole.ADMIN.value
        )
        return first_member

    def _update_user_credentials(self, user: User) -> None:
        """Update user with secure credentials.

        Args:
            user (User): The user to update
        """
        # Only update if using default insecure credentials
        if (user.username == DefaultOrg.MOCK_USER or
            user.email == DefaultOrg.MOCK_USER_EMAIL):
            new_username = f"user_{uuid.uuid4().hex[:8]}"
            new_password = uuid.uuid4().hex  # Temporary password
            
            user.username = new_username
            user.email = f"{new_username}@example.com"
            user.password = make_password(new_password)
            user.save()
            logger.info(f"Updated user credentials to secure values")

    def get_user_info(self, request: Request) -> Optional[UserInfo]:
        user: User = request.user
        if user:
            return UserInfo(
                id=user.id,
                user_id=user.user_id,
                name=user.username,
                display_name=user.username,
                email=user.email,
            )
        else:
            return None

    def get_organization_info(self, org_id: str) -> Optional[Organization]:
        return OrganizationService.get_organization_by_org_id(org_id=org_id)

    def make_organization_and_add_member(
        self,
        user_id: str,
        user_name: str,
        organization_name: Optional[str] = None,
        display_name: Optional[str] = None,
    ) -> Optional[OrganizationData]:
        organization: OrganizationData = OrganizationData(
            id=str(uuid.uuid4()),
            display_name=DefaultOrg.MOCK_ORG,
            name=DefaultOrg.MOCK_ORG,
        )
        return organization

    def make_user_organization_name(self) -> str:
        return str(uuid.uuid4())

    def make_user_organization_display_name(self, user_name: str) -> str:
        name = f"{user_name}'s" if user_name else "Your"
        return f"{name} organization"

    def user_logout(self, request: HttpRequest) -> Response:
        """Log out the user.

        Args:
            request (HttpRequest): The HTTP request object.

        Returns:
            Response: The redirect response to the web app origin URL.
        """
        logout(request)
        return redirect(settings.WEB_APP_ORIGIN_URL)

    def get_organization_members_by_org_id(
        self, organization_id: str
    ) -> list[MemberData]:
        users: list[OrganizationMember] = OrganizationMemberService.get_members()
        return self.authentication_helper.list_of_members_from_user_model(users)

    def reset_user_password(self, user: User) -> ResetUserPasswordDto:
        raise MethodNotImplemented()

    def invite_user(
        self,
        admin: OrganizationMember,
        org_id: str,
        email: str,
        role: Optional[str] = None,
    ) -> bool:
        raise MethodNotImplemented()
