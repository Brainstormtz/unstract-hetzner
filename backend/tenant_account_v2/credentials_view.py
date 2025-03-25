import logging
import os
from typing import Dict, Any

from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from account_v2.authentication_controller import AuthenticationController
from account_v2.custom_exceptions import Forbidden
from tenant_account_v2.organization_member_service import OrganizationMemberService
from tenant_account_v2.serializer import CredentialsSerializer

logger = logging.getLogger(__name__)

ENV_FILE_PATH = os.path.join(settings.BASE_DIR, '.env')

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_default_credentials(request: Request) -> Response:
    """
    Get the default authentication credentials.
    
    Only admin users can access this endpoint.
    
    Returns:
        Response: The default username and password.
    """
    # Check if user is admin
    auth_controller = AuthenticationController()
    org_member = OrganizationMemberService.get_user_by_id(id=request.user.id)
    if not auth_controller.is_organization_admin(org_member):
        raise Forbidden()
    
    # Get default credentials from environment variables
    username = os.environ.get('DEFAULT_AUTH_USERNAME', '')
    password = os.environ.get('DEFAULT_AUTH_PASSWORD', '')
    
    return Response(
        status=status.HTTP_200_OK,
        data={
            'username': username,
            'password': password
        }
    )

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_default_credentials(request: Request) -> Response:
    """
    Update the default authentication credentials.
    
    Only admin users can update the credentials.
    
    Args:
        request (Request): The HTTP request object containing the new credentials.
        
    Returns:
        Response: Success or error message.
    """
    # Check if user is admin
    auth_controller = AuthenticationController()
    org_member = OrganizationMemberService.get_user_by_id(id=request.user.id)
    if not auth_controller.is_organization_admin(org_member):
        raise Forbidden()
    
    # Validate request data
    serializer = CredentialsSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(
            status=status.HTTP_400_BAD_REQUEST,
            data={'error': serializer.errors}
        )
    
    username = serializer.validated_data.get('username')
    password = serializer.validated_data.get('password')
    
    try:
        # Update environment variables
        os.environ['DEFAULT_AUTH_USERNAME'] = username
        os.environ['DEFAULT_AUTH_PASSWORD'] = password
        
        # Update .env file
        update_env_file('DEFAULT_AUTH_USERNAME', username)
        update_env_file('DEFAULT_AUTH_PASSWORD', password)
        
        return Response(
            status=status.HTTP_200_OK,
            data={'message': 'Default credentials updated successfully'}
        )
    except Exception as e:
        logger.error(f"Error updating default credentials: {str(e)}")
        return Response(
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            data={'error': 'Failed to update default credentials'}
        )

def update_env_file(key: str, value: str) -> None:
    """
    Update a key-value pair in the .env file.
    
    Args:
        key (str): The environment variable key.
        value (str): The new value for the environment variable.
    """
    if not os.path.exists(ENV_FILE_PATH):
        logger.warning(f".env file not found at {ENV_FILE_PATH}")
        return
    
    # Read the current .env file
    with open(ENV_FILE_PATH, 'r') as file:
        lines = file.readlines()
    
    # Update the key-value pair
    updated = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}\n"
            updated = True
            break
    
    # Add the key-value pair if it doesn't exist
    if not updated:
        lines.append(f"{key}={value}\n")
    
    # Write the updated content back to the .env file
    with open(ENV_FILE_PATH, 'w') as file:
        file.writelines(lines)
