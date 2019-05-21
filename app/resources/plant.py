import os
from datetime import datetime

from flask import current_app, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from flask_restful import Resource

from app.custom import admin_required
from app.models import db
from app.models.disease import DiseaseModel
from app.models.image import ImageModel
from app.models.plant import PlantModel
from app.models.user import UserModel
from app.predict import predict_disease
from app.schemas.image import ImageModelSchema, ImageSchema
from app.schemas.plant import PlantSchema
from app.utils import delete_image, save_image

plant_schema = PlantSchema()
plant_list_schema = PlantSchema(many=True)
img_schema = ImageModelSchema()
image_schema = ImageSchema()


# for plants
class Plants(Resource):
    # Get all plants
    @classmethod
    @jwt_required
    def get(cls):
        return {"plants": plant_list_schema.dump(PlantModel.find_all())}, 200

    # Register a plant
    @classmethod
    @admin_required
    def post(cls):
        plant_data = plant_schema.load(request.get_json())
        plant = PlantModel.find_by_name(plant_data.name)
        if plant:
            current_app.logger.debug(f"Plant<{plant_data.name}> already registered.")   # noqa
            return {"msg": f"Plant[name={plant.name}] already registered."}, 400        # noqa
        try:
            current_app.logger.info(f"Registered {plant_data}")
            plant_data.save_to_db()
            return {"msg": "Plant has been successfully registered"}, 201
        except Exception as err:
            current_app.logger.error(err)
            return {"msg": "Failed to register the plant"}, 500


# for plant by ID
class PlantsID(Resource):
    # Get plant
    @classmethod
    @jwt_required
    def get(cls, plant_id: int):
        plant = PlantModel.find_by_id(plant_id)
        if plant:
            return plant_schema.dump(plant), 200
        return {"msg": f"Plant[id={plant_id}] not found."}, 404

    # Update plant's info
    @classmethod
    @admin_required
    def put(cls, plant_id: int):
        data = plant_schema.load(request.get_json())
        plant = PlantModel.find_by_id(plant_id)
        if plant:
            plant.name = data.name
            plant.save_to_db()
            current_app.logger.info(f"Updated {plant}")
            return {"msg": "Plant's info has been successfully updated"}, 200
        return {"msg": f"Plant[id={plant_id}] not found."}, 404

    # Delete plant
    @classmethod
    @admin_required
    def delete(cls, plant_id: int):
        plant = PlantModel.find_by_id(plant_id)
        if plant:
            plant.delete_from_db()
            current_app.logger.info(f"Deleted {plant}")
            return {"msg": f"Plant has been successfully deleted."}, 200
        return {"msg": f"Plant[id={plant_id}] not found."}, 404


# Get all images of a plant
class PlantsImages(Resource):
    @classmethod
    @admin_required
    def get(cls, plant_id):
        plant = PlantModel.find_by_id(plant_id)
        if plant is None:
            return {"msg": f"Plant[id={plant_id}] not found."}, 404
        return {"images": plant_list_schema.dump(ImageModel.findAll_by_plant(plant_id))}, 200  # noqa

    @classmethod
    @jwt_required
    def post(cls, plant_id: int):
        image = image_schema.load(request.files)["image"]
        user_id = get_jwt_identity()
        user = UserModel.find_by_id(user_id)
        plant = PlantModel.find_by_id(plant_id)
        if plant is None:
            return {"message": "Wrong plant id provided."}, 400

        user_folder = user.user_dir
        ext = os.path.splitext(image.filename)[1]
        upload_dt = datetime.now()
        dt_format = f"user{user_id}_%H:%M:%S_%d-%m-%Y"
        image.filename = upload_dt.strftime(dt_format) + ext

        # Check for allowed image extensions
        if ext[1:] not in current_app.config["ALLOWED_IMAGE_EXT"]:
            return {"messages": f"Extension {ext} not allowed."}, 400

        # save client image on disk
        # file should be of image type only
        try:
            image_path = save_image(image, folder=user_folder)
        except:     # noqa
            return {"message": "Not a valid image"}, 400

        # predict the disease
        try:
            model_path = os.path.join(current_app.config["APP_DIR_PATH"],
                                      'disease_prediction_models',
                                      plant.name)
            result = predict_disease(image_path, model_path)
            disease = DiseaseModel.find_by_plant(name=result["Disease"],
                                                 plant_id=plant.id)
            # Check if disease name is properly registerd
            if disease is None:
                current_app.logger.error(f"Predicted disease <{result['Disease']}> not found!")    # noqa
                delete_image(image_path)
                return {"message": "The server encountered an internal error and was unable to complete your request"}, 500     # noqa

        except Exception as e:     # noqa 
            current_app.logger.error(e.args[0])
            delete_image(image_path)
            return {"message": "The server encountered an internal error and was unable to complete your request"}, 500     # noqa

        # save image into database
        try:
            image_data = ImageModel(
                image_path=image_path, plant_id=plant.id,
                user_id=user_id, disease_id=disease.id,
                upload_date=upload_dt,
            )
            db.session.add(image_data)
            db.session.commit()
        except Exception as e:     # noqa
            current_app.logger.error(e.args[0])
            delete_image(image_path)
            return {"message": "The server encountered an internal error and was unable to complete your request"}, 500     # noqa
        # if all above processes completed successfully, then return result
        return result, 200


# Get all disease of a plant
class PlantsDiseases(Resource):
    @classmethod
    @jwt_required
    def get(cls, plant_id):
        plant = PlantModel.find_by_id(plant_id)
        if plant is None:
            return {"msg": f"Plant[id={plant_id}] not found."}, 404
        return {"diseases": plant_list_schema.dump(DiseaseModel.findAll_by_plant(plant_id))}, 200  # noqa
