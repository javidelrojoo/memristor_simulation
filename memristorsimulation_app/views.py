import json

from django.http import HttpResponse, JsonResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from memristorsimulation_app.serializers.simulation import SimulationInputsSerializer
from django.shortcuts import render
from memristorsimulation_app.services.simulationservice import SimulationService
import base64


class SimulationView(APIView):
    def post(self, request):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        serializer = SimulationInputsSerializer(data=data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        validated_data = serializer.validated_data

        try:
            simulation_service = SimulationService(request_parameters=validated_data)
            zip_buffer = simulation_service.simulate_and_create_results_zip()
            
            zip_bytes = zip_buffer.getvalue()
            zip_base64 = base64.b64encode(zip_bytes).decode("utf-8")
            
            folder_name = simulation_service.simulation_inputs.export_parameters.folder_name
            
            return JsonResponse({
                "zip_base64": zip_base64,
                "folder_name": folder_name,
                "file_size": len(zip_bytes),
            })

        except Exception as e:
            import traceback
            return JsonResponse(
                {
                    "ERROR": f"Simulation and export failed: {str(e)}"
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def get(self, request):
        return render(request, "form.html", {})
