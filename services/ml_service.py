import fasttext


class FastTextService:
    def __init__(self):
        self.model = None
        self.model_path = None

    def load(self, model_path):
        if self.model is not None and self.model_path == model_path:
            return self.model

        self.model = fasttext.load_model(model_path)
        self.model_path = model_path
        print(f"Model FastText loaded successfully from {model_path}")
        return self.model

    def is_ready(self):
        return self.model is not None

    def predict(self, text):
        if self.model is None:
            raise RuntimeError('Model not loaded')

        cleaned_text = (text or '').lower().strip()
        prediction = self.model.predict(cleaned_text, k=1)
        intent = prediction[0][0].replace('__label__', '')
        confidence = float(prediction[1][0])
        return intent, confidence


ml_service = FastTextService()
