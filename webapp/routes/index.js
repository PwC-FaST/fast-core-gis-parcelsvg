var express = require('express');
var router = express.Router();
var axios = require('axios');

host = process.env.MONGODB_HOST || 'localhost'
port = process.env.MONGODB_PORT || 27017
db = process.env.TARGET_DB || 'fast'
lpisCollection = process.env.LPIS_COLLECTION || 'lpis'

urlPrefix = process.env.FRONTEND_URL_PREFIX || '/'

geojson2svgServiceHost = process.env.SVG_RENDERING_SERVICE_HOST || 'localhost'
geojson2svgServicePort = process.env.SVG_RENDERING_SERVICE_PORT || '8080'

geojson2svgWS = 'http://' + geojson2svgServiceHost + ':' + geojson2svgServicePort;

if (urlPrefix.slice(-1) != '/') {
    urlPrefix += '/'
}

// Mongoose import
var mongoose = require('mongoose');

// Mongoose connection to MongoDB
mongoose.connect('mongodb://' + host + ':' + port + '/' + db, { useNewUrlParser: true }, function (error) {
    if (error) {
        console.log(error);
    }
});

// Mongoose Schema definition
var Schema = mongoose.Schema;

var ParcelSchema = new Schema({
    _id: Schema.Types.String,
    geometry: {
      coordinates: []
    }
})

// Mongoose Model definition
var Parcel = mongoose.model('JString', ParcelSchema, lpisCollection);


router.post('/', function (req, res) {
    if (req) {
        ids =  req.body.primary.concat(req.body.secondary);

        Parcel.find({_id: { $in: ids}}, function (err, parcels) {
            if (err) {
                res.status(500).send({ "error": err })
            } else {

                fc = {
                    type: "FeatureCollection",
                    features: parcels.map(function (p) {

                        feature = p.toJSON();
                        var isPrimary =  req.body.primary.includes(feature._id);

                        feature.properties.inZoomBox = isPrimary;
                        feature.properties.plot = {
                            class: isPrimary ? "primary-parcel" : "secondary-parcel",
                            "parcel-id": feature._id };

                        return feature;
                    })
                };

                axios.post(geojson2svgWS,fc)
                    .then(function (response) {
                        res.setHeader('content-type', response.headers['content-type']);
                        res.send(response.data);
                    })
                    .catch(function (err) {
                        if (err.response) {
                            // that falls out of the range of 2xx
                            console.log(err)
                            res.status(500).send({
                                error: "Error while requesting the svg rendering service !"})
                        } else if (err.request) {
                            // The request was made but no response was received
                            console.log(err.request);
                            res.status(500).send({ error: "SVG rendering service not reachable !"})
                        } else {
                            // Something happened in setting up the request that triggered an Error
                            console.log('Error', err.message);
                            res.status(500).send()
                        }
                    })
            }
        })
    }
})

router.get('/healthz', function(req,res) {
    status = 200
    if (mongoose.connection.readyState != 1) {
        status = 500
    } else {
        Parcel.findOne(function(err, doc) {
            if (err) {
                status = 500
            }
        })

    }
    
    res.status(status).send();
});

module.exports = router;
