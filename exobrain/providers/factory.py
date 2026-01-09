"""Model factory for creating model providers."""


from exobrain.config import Config, ModelProviderConfig
from exobrain.providers.base import ModelProvider
from exobrain.providers.gemini_provider import GeminiProvider
from exobrain.providers.local_provider import LocalModelProvider
from exobrain.providers.openai_provider import OpenAIProvider


class ModelFactory:
    """Factory for creating model providers."""

    def __init__(self, config: Config):
        """Initialize model factory.

        Args:
            config: Application configuration
        """
        self.config = config
        self._providers: dict[str, ModelProvider] = {}

    def get_provider(self, model_spec: str | None = None) -> ModelProvider:
        """Get a model provider by specification.

        Args:
            model_spec: Model specification in format "provider/model" or None for default

        Returns:
            ModelProvider instance

        Raises:
            ValueError: If model specification is invalid
        """
        if model_spec is None:
            model_spec = self.config.models.default

        # Parse model specification
        if "/" in model_spec:
            provider_name, model_name = model_spec.split("/", 1)
        else:
            # First, try to find a provider with this name
            provider_config = self.config.models.providers.get(model_spec)
            if provider_config and provider_config.get_model_list():
                # It's a provider name, use first model
                provider_name = model_spec
                model_name = provider_config.get_model_list()[0]
            else:
                # Search for the model name across all providers
                found_provider = None
                for pname, pconfig in self.config.models.providers.items():
                    if model_spec in pconfig.get_model_list():
                        found_provider = pname
                        break

                if found_provider:
                    provider_name = found_provider
                    model_name = model_spec
                else:
                    raise ValueError(
                        f"Invalid model specification: {model_spec}. "
                        f"Use format 'provider/model' (e.g., 'openai/gpt-4o')"
                    )

        # Check cache
        cache_key = f"{provider_name}/{model_name}"
        if cache_key in self._providers:
            return self._providers[cache_key]

        # Get provider configuration
        provider_config = self.config.models.providers.get(provider_name)
        if not provider_config:
            raise ValueError(f"Unknown provider: {provider_name}")

        # Create provider
        provider = self._create_provider(provider_name, model_name, provider_config)
        self._providers[cache_key] = provider

        return provider

    def _create_provider(
        self,
        provider_name: str,
        model_name: str,
        config: ModelProviderConfig,
    ) -> ModelProvider:
        """Create a model provider instance.

        Args:
            provider_name: Name of the provider
            model_name: Name of the model
            config: Provider configuration

        Returns:
            ModelProvider instance

        Raises:
            ValueError: If provider type is unknown
        """
        # Get model-specific default params (with fallback to provider-level)
        default_params = config.get_model_default_params(model_name)

        if provider_name == "openai":
            if not config.api_key:
                raise ValueError("OpenAI API key is required")
            return OpenAIProvider(
                api_key=config.api_key,
                base_url=config.base_url or "https://api.openai.com/v1",
                model=model_name,
                default_params=default_params,
            )

        elif provider_name == "gemini":
            if not config.api_key:
                raise ValueError("Gemini API key is required")
            return GeminiProvider(
                api_key=config.api_key,
                model=model_name,
                base_url=config.base_url or "https://generativelanguage.googleapis.com/v1beta",
                default_params=default_params,
            )

        elif provider_name == "local" or provider_name == "ollama":
            if not config.base_url:
                raise ValueError(f"{provider_name} requires base_url configuration")
            return LocalModelProvider(
                base_url=config.base_url,
                model=model_name,
                api_key=config.api_key or "dummy",
                default_params=default_params,
            )

        else:
            # Treat all other providers as OpenAI-compatible APIs
            # This allows users to add custom third-party providers
            if not config.api_key:
                raise ValueError(f"{provider_name} API key is required")
            if not config.base_url:
                raise ValueError(f"{provider_name} requires base_url configuration")
            return OpenAIProvider(
                api_key=config.api_key,
                base_url=config.base_url,
                model=model_name,
                default_params=default_params,
            )

    def list_available_models(self) -> list[str]:
        """List all available model specifications.

        Returns:
            List of model specifications in format "provider/model"
        """
        models = []
        for provider_name, provider_config in self.config.models.providers.items():
            for model_name in provider_config.get_model_list():
                models.append(f"{provider_name}/{model_name}")
        return models
