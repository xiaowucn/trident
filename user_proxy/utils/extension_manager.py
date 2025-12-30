from user_proxy.config import get_config


class ExtensionManager:
    ENV_EXTENSION_MAPPING = {
        'chasing': [],
    }

    BACKEND_EXTENSION_MAPPING = {
        'gaussdb': [],
        'tdsql': [],
    }

    # funcs: alter_sequence_data_type,func_jsonb_set
    # extensions: postgis,btree_gist,btree_gin

    @classmethod
    def is_active_extension(cls, name):
        extensions = cls.ENV_EXTENSION_MAPPING.get(get_config('sys'))
        if extensions is None:
            extensions = cls.BACKEND_EXTENSION_MAPPING.get(get_config('webif.postgresql.backend') or 'postgres')
            if extensions is None:
                return True
        if name in extensions:
            return True
        return False

    @classmethod
    def create_extension(cls, op, name):
        if cls.is_active_extension(name):
            op.execute(f'CREATE EXTENSION if not exists {name}')
